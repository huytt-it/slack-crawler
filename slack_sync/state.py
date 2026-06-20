"""Watermark (sync state) persistence.

Stores per-channel high-water marks as a JSON file. Watermarks are only advanced
after a channel finishes syncing so a mid-run crash never corrupts state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WatermarkStore:
    """File-backed per-channel watermark store."""

    def __init__(self, state_dir: str) -> None:
        self._path = Path(state_dir) / "watermarks.json"
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info("Loaded watermarks for %d channels.", len(self._data))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        tmp.replace(self._path)

    def get(self, channel_id: str) -> str | None:
        return self._data.get(channel_id)

    def set(self, channel_id: str, ts: str) -> None:
        """Advance the watermark and persist atomically."""
        self._data[channel_id] = ts
        self._save()
        logger.debug("Watermark for %s advanced to %s.", channel_id, ts)
