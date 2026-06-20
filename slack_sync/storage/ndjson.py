"""NDJSON file storage backend — one directory per channel, append-friendly.

Structure:
    output/
    ├── general/
    │   ├── messages.ndjson      # normalized fields (lean, for analytics/RAG)
    │   ├── raw.ndjson           # original Slack payloads (only if store_raw)
    │   ├── _files_index.json
    │   └── files/
    └── _users.json

`raw` is written to a separate file so messages.ndjson stays compact. Channels
sync in parallel but each writes only its own directory, so no cross-thread file
contention occurs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from slack_sync.storage import StorageBackend

logger = logging.getLogger(__name__)


class NdjsonBackend(StorageBackend):
    def __init__(self, output_dir: str, store_raw: bool = True) -> None:
        self._dir = Path(output_dir)
        self._store_raw = store_raw
        self._dir.mkdir(parents=True, exist_ok=True)

    def store_messages(self, channel_id: str, channel_name: str, messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0

        safe_name = channel_name.replace("/", "_").replace("\\", "_")
        channel_dir = self._dir / safe_name
        channel_dir.mkdir(parents=True, exist_ok=True)

        msg_path = channel_dir / "messages.ndjson"
        raw_path = channel_dir / "raw.ndjson"

        raw_f = open(raw_path, "a", encoding="utf-8") if self._store_raw else None
        try:
            with open(msg_path, "a", encoding="utf-8") as f:
                for msg in messages:
                    record = {k: v for k, v in msg.items() if k != "raw"}
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    if raw_f is not None:
                        raw_f.write(json.dumps(
                            {"channel_id": channel_id, "ts": msg.get("ts"), "raw": msg.get("raw")},
                            ensure_ascii=False, default=str,
                        ) + "\n")
        finally:
            if raw_f is not None:
                raw_f.close()

        logger.info("Appended %d messages to %s.", len(messages), msg_path)
        return len(messages)

    def store_users(self, users: dict[str, dict[str, Any]]) -> None:
        path = self._dir / "_users.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Wrote user mapping (%d users) to %s.", len(users), path)

    def close(self) -> None:
        pass
