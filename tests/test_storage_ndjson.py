"""Tests for NDJSON storage backend."""

from __future__ import annotations

import json
from slack_sync.storage.ndjson import NdjsonBackend


class TestNdjsonBackend:
    def test_store_messages(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        messages = [
            {"channel_id": "C1", "ts": "100.0", "text": "hello", "channel_name": "general",
             "user_id": "U1", "datetime_utc": "2025-01-01T00:00:00+00:00", "type": "message",
             "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0, "raw": {}},
            {"channel_id": "C1", "ts": "101.0", "text": "world", "channel_name": "general",
             "user_id": "U2", "datetime_utc": "2025-01-01T00:01:00+00:00", "type": "message",
             "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0, "raw": {}},
        ]

        count = backend.store_messages("C1", "general", messages)
        assert count == 2

        path = tmp_path / "out" / "general.ndjson"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "hello"
        assert json.loads(lines[1])["text"] == "world"

    def test_append_on_second_run(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        msg1 = [{"channel_id": "C1", "ts": "100.0", "text": "first", "channel_name": "g",
                  "user_id": "U1", "datetime_utc": None, "type": "message",
                  "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0, "raw": {}}]
        msg2 = [{"channel_id": "C1", "ts": "101.0", "text": "second", "channel_name": "g",
                  "user_id": "U1", "datetime_utc": None, "type": "message",
                  "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0, "raw": {}}]

        backend.store_messages("C1", "g", msg1)
        backend.store_messages("C1", "g", msg2)

        lines = (tmp_path / "out" / "g.ndjson").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_store_empty_returns_zero(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        assert backend.store_messages("C1", "general", []) == 0

    def test_store_users(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        users = {
            "U1": {"id": "U1", "display_name": "alice", "real_name": "Alice", "email": "a@x.com"},
            "U2": {"id": "U2", "display_name": "bob", "real_name": "Bob", "email": None},
        }
        backend.store_users(users)

        path = tmp_path / "out" / "_users.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data["U1"]["display_name"] == "alice"
