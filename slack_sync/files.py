"""File attachment downloader for Slack messages."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class FileDownloader:
    """Downloads file attachments from Slack using the API token."""

    def __init__(self, token: str, output_dir: str, max_retries: int = 3) -> None:
        self._token = token
        self._output_dir = Path(output_dir)
        self._max_retries = max_retries
        self._downloaded: set[str] = set()

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
            return []

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

        return results

    def _download_file(self, url: str, dest: Path) -> bool:
        """Download a single file with retry logic."""
        headers = {"Authorization": f"Bearer {self._token}"}

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=60)

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
