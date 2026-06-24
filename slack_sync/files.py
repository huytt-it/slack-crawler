"""File attachment downloader for Slack messages.

Production notes:
- A thread-local requests.Session reuses TCP/TLS connections (keep-alive),
  avoiding a fresh handshake per file.
- Files within a page download concurrently via an internal thread pool.
- Large files stream to a temp file then atomically rename; an optional size
  cap skips oversized attachments before downloading.
- The in-memory file index is guarded by a lock and flushed per channel.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class FileDownloader:
    def __init__(
        self,
        token: str,
        output_dir: str,
        max_retries: int = 3,
        max_file_size_mb: int = 0,
        workers: int = 4,
    ) -> None:
        self._token = token
        self._output_dir = Path(output_dir)
        self._max_retries = max_retries
        self._max_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else 0
        self._workers = max(1, workers)
        self._downloaded: set[str] = set()
        self._file_index: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._local = threading.local()

    @property
    def downloaded_count(self) -> int:
        with self._lock:
            return len(self._downloaded)

    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

    def process_page_files(self, messages: list[dict[str, Any]], channel_name: str) -> None:
        """Download attachments for all messages in a page concurrently."""
        targets = [m for m in messages if m.get("raw", {}).get("files")]
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for msg, downloaded in zip(targets, pool.map(
                lambda m: self.download_message_files(m, channel_name), targets
            )):
                if downloaded:
                    msg["downloaded_files"] = downloaded

    def download_message_files(self, msg: dict[str, Any], channel_name: str) -> list[dict[str, str]]:
        """Download all files attached to a single message."""
        raw = msg.get("raw", {})
        files = raw.get("files", [])
        if not files:
            return []

        safe_channel = channel_name.replace("/", "_").replace("\\", "_")
        files_dir = self._output_dir / safe_channel / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, str]] = []
        for file_info in files:
            file_id = file_info.get("id", "")
            if not file_id:
                continue

            if file_info.get("mode", "") in ("tombstone", "hidden_by_limit"):
                continue

            size = file_info.get("size", 0)
            if self._max_bytes and size and size > self._max_bytes:
                logger.warning(
                    "Skipping %s (%d bytes) — exceeds max file size.",
                    file_info.get("name", file_id), size,
                )
                continue

            url = file_info.get("url_private_download") or file_info.get("url_private", "")
            if not url:
                continue

            original_name = file_info.get("name", "unknown")
            safe_name = f"{file_id}_{self._sanitize_filename(original_name)}"
            local_path = files_dir / safe_name

            with self._lock:
                already = file_id in self._downloaded
            if already or local_path.exists():
                with self._lock:
                    self._downloaded.add(file_id)
                results.append({"file_id": file_id, "name": original_name, "local_path": str(local_path)})
                continue

            if self._download_file(url, local_path):
                with self._lock:
                    self._downloaded.add(file_id)
                results.append({"file_id": file_id, "name": original_name, "local_path": str(local_path)})

        for r in results:
            self._add_to_index(safe_channel, r, msg, raw)
        return results

    def _add_to_index(
        self, channel_key: str, file_result: dict[str, str],
        msg: dict[str, Any], raw: dict[str, Any],
    ) -> None:
        file_meta = next((f for f in raw.get("files", []) if f.get("id") == file_result["file_id"]), {})
        entry = {
            "file_id": file_result["file_id"],
            "file_name": file_result["name"],
            "local_path": file_result["local_path"],
            "channel_id": msg.get("channel_id", ""),
            "channel_name": msg.get("channel_name", ""),
            "sender_user_id": msg.get("user_id", ""),
            "message_ts": msg.get("ts", ""),
            "datetime_utc": msg.get("datetime_utc", ""),
            "thread_ts": msg.get("thread_ts"),
            "message_text": msg.get("text", ""),
            "filetype": file_meta.get("filetype", ""),
            "size_bytes": file_meta.get("size", 0),
        }
        with self._lock:
            self._file_index.setdefault(channel_key, []).append(entry)

    def save_file_indexes(self) -> None:
        """Write _files_index.json for every channel that had downloads."""
        with self._lock:
            channels = list(self._file_index.keys())
        for channel_key in channels:
            self._flush_channel(channel_key)

    def _flush_channel(self, channel_key: str) -> None:
        with self._lock:
            entries = self._file_index.pop(channel_key, [])
        if not entries:
            return
        index_path = self._output_dir / channel_key / "_files_index.json"
        existing: list[dict[str, Any]] = []
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        seen_ids = {e["file_id"] for e in existing}
        for entry in entries:
            if entry["file_id"] not in seen_ids:
                existing.append(entry)
                seen_ids.add(entry["file_id"])
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Wrote file index (%d files) to %s.", len(existing), index_path)

    def _download_file(self, url: str, dest: Path) -> bool:
        """Download a single file, following Slack's auth-preserving redirect."""
        headers = {"Authorization": f"Bearer {self._token}"}
        session = self._session()

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = session.get(url, headers=headers, stream=True, timeout=60, allow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_url = resp.headers.get("Location", "")
                    if redirect_url:
                        resp = session.get(redirect_url, headers=headers, stream=True, timeout=60)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    logger.warning("Rate limited downloading file. Retrying in %ds.", retry_after)
                    time.sleep(retry_after)
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        "Failed to download %s: HTTP %d (attempt %d/%d).",
                        dest.name, resp.status_code, attempt, self._max_retries,
                    )
                    if attempt < self._max_retries:
                        time.sleep(min(2 ** attempt, 30))
                    continue

                tmp = dest.with_suffix(dest.suffix + ".tmp")
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                tmp.replace(dest)
                return True

            except requests.RequestException as e:
                logger.warning(
                    "Error downloading %s: %s (attempt %d/%d).",
                    dest.name, e, attempt, self._max_retries,
                )
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 30))

        logger.error("Failed to download %s after %d attempts.", dest.name, self._max_retries)
        return False

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        forbidden = '<>:"/\\|?*'
        result = "".join(c if c not in forbidden else "_" for c in name)
        return result.strip(". ") or "file"
