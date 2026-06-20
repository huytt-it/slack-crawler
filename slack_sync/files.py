"""File attachment downloader for Slack messages."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


class FileDownloader:
    """Downloads file attachments from Slack using the API token."""

    def __init__(self, token: str, output_dir: str, max_retries: int = 3) -> None:
        self._token = token
        self._output_dir = Path(output_dir)
        self._max_retries = max_retries
        self._downloaded: set[str] = set()
        self._file_index: dict[str, list[dict[str, Any]]] = {}

    def download_message_files(
        self, msg: dict[str, Any], channel_name: str,
    ) -> list[dict[str, str]]:
        """Download all files attached to a message.

        Returns a list of dicts with file_id, name, and local_path for each
        successfully downloaded file.
        """
        raw = msg.get("raw", {})
        files = raw.get("files", [])
        if not files:
            logger.debug("Message %s has no files in raw payload.", msg.get("ts", "?"))
            return []

        logger.info("Message %s has %d file(s) to download.", msg.get("ts", "?"), len(files))

        safe_channel = channel_name.replace("/", "_").replace("\\", "_")
        files_dir = self._output_dir / safe_channel / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, str]] = []
        for file_info in files:
            file_id = file_info.get("id", "")
            if not file_id:
                continue

            mode = file_info.get("mode", "")
            if mode in ("tombstone", "hidden_by_limit"):
                logger.debug("Skipping deleted/hidden file %s.", file_id)
                continue

            url = file_info.get("url_private_download") or file_info.get("url_private", "")
            if not url:
                logger.debug("File %s has no download URL, skipping.", file_id)
                continue

            original_name = file_info.get("name", "unknown")
            safe_name = f"{file_id}_{self._sanitize_filename(original_name)}"
            local_path = files_dir / safe_name

            if file_id in self._downloaded or local_path.exists():
                results.append({
                    "file_id": file_id,
                    "name": original_name,
                    "local_path": str(local_path),
                })
                self._downloaded.add(file_id)
                continue

            if self._download_file(url, local_path):
                self._downloaded.add(file_id)
                results.append({
                    "file_id": file_id,
                    "name": original_name,
                    "local_path": str(local_path),
                })
                logger.debug("Downloaded %s -> %s", original_name, local_path)

        if results:
            for r in results:
                self._add_to_index(safe_channel, r, msg, raw)

        return results

    def _add_to_index(
        self, channel_key: str, file_result: dict[str, str],
        msg: dict[str, Any], raw: dict[str, Any],
    ) -> None:
        """Add a downloaded file entry to the in-memory index."""
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
            "filetype": next(
                (f.get("filetype", "") for f in raw.get("files", [])
                 if f.get("id") == file_result["file_id"]),
                "",
            ),
            "size_bytes": next(
                (f.get("size", 0) for f in raw.get("files", [])
                 if f.get("id") == file_result["file_id"]),
                0,
            ),
        }
        self._file_index.setdefault(channel_key, []).append(entry)

    def save_file_indexes(self) -> None:
        """Write _files_index.json for each channel that had downloads."""
        for channel_key, entries in self._file_index.items():
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
        """Download a single file with retry logic.

        Slack returns a 302 redirect to a CDN URL. requests strips the
        Authorization header on cross-domain redirects, so we follow
        redirects manually to preserve the token.
        """
        headers = {"Authorization": f"Bearer {self._token}"}

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=False)

                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_url = resp.headers.get("Location", "")
                    if redirect_url:
                        resp = requests.get(redirect_url, headers=headers, stream=True, timeout=60)

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
                    for chunk in resp.iter_content(chunk_size=8192):
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
        """Remove characters that are invalid in file names."""
        forbidden = '<>:"/\\|?*'
        result = "".join(c if c not in forbidden else "_" for c in name)
        return result.strip(". ") or "file"
