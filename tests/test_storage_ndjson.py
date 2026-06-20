"""Tests for NDJSON storage backend."""

from __future__ import annotations

import json
from slack_sync.storage.ndjson import NdjsonBackend


def _make_msg(**overrides):
    base = {
        "channel_id": "C1", "ts": "100.0", "text": "hello", "channel_name": "general",
        "user_id": "U1", "datetime_utc": "2025-01-01T00:00:00+00:00", "type": "message",
        "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0,
        "raw": {"ts": "100.0", "text": "hello", "blocks": ["..."]},
    }
    base.update(overrides)
    return base


class TestNdjsonBackend:
    def test_messages_exclude_raw(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_messages("C1", "general", [_make_msg()])

        msg_path = tmp_path / "out" / "general" / "messages.ndjson"
        record = json.loads(msg_path.read_text(encoding="utf-8").strip())
        assert "raw" not in record
        assert record["text"] == "hello"

    def test_raw_written_to_separate_file(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"), store_raw=True)
        backend.store_messages("C1", "general", [_make_msg()])

        raw_path = tmp_path / "out" / "general" / "raw.ndjson"
        record = json.loads(raw_path.read_text(encoding="utf-8").strip())
        assert record["ts"] == "100.0"
        assert record["raw"]["blocks"] == ["..."]

    def test_store_raw_disabled(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"), store_raw=False)
        backend.store_messages("C1", "general", [_make_msg()])
        assert not (tmp_path / "out" / "general" / "raw.ndjson").exists()

    def test_append_on_second_run(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_messages("C1", "general", [_make_msg(ts="100.0", text="first")])
        backend.store_messages("C1", "general", [_make_msg(ts="101.0", text="second")])

        lines = (tmp_path / "out" / "general" / "messages.ndjson").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_separate_dirs_per_channel(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_messages("C1", "general", [_make_msg()])
        backend.store_messages("C2", "random", [_make_msg(channel_id="C2", channel_name="random")])

        assert (tmp_path / "out" / "general" / "messages.ndjson").exists()
        assert (tmp_path / "out" / "random" / "messages.ndjson").exists()

    def test_store_empty_returns_zero(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        assert backend.store_messages("C1", "general", []) == 0

    def test_store_users(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        users = {"U1": {"id": "U1", "display_name": "alice", "real_name": "Alice", "email": "a@x.com"}}
        backend.store_users(users)
        data = json.loads((tmp_path / "out" / "_users.json").read_text(encoding="utf-8"))
        assert data["U1"]["display_name"] == "alice"
