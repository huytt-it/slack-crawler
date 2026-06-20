"""NDJSON file storage backend — one directory per channel, append-friendly."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from slack_sync.storage import StorageBackend

logger = logging.getLogger(__name__)


class NdjsonBackend(StorageBackend):
    """Writes messages as newline-delimited JSON, one directory per channel.

    Structure:
        output/
        ├── general/
        │   └── messages.ndjson
        ├── engineering/
        │   └── messages.ndjson
        └── _users.json
    """

    def __init__(self, output_dir: str) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def store_messages(self, channel_id: str, channel_name: str, messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0

        safe_name = channel_name.replace("/", "_").replace("\\", "_")
        channel_dir = self._dir / safe_name
        channel_dir.mkdir(parents=True, exist_ok=True)
        path = channel_dir / "messages.ndjson"

        with open(path, "a", encoding="utf-8") as f:
            for msg in messages:
                serializable = dict(msg)
                f.write(json.dumps(serializable, ensure_ascii=False, default=str) + "\n")

        logger.info("Appended %d messages to %s.", len(messages), path)
        return len(messages)

    def store_users(self, users: dict[str, dict[str, Any]]) -> None:
        path = self._dir / "_users.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Wrote user mapping (%d users) to %s.", len(users), path)

    def close(self) -> None:
        pass
