"""Tests for NDJSON storage backend."""

from __future__ import annotations

import json
from slack_sync.storage.ndjson import NdjsonBackend


def _make_msg(**overrides):
    base = {
        "channel_id": "C1", "ts": "100.0", "text": "hello", "channel_name": "general",
        "user_id": "U1", "datetime_utc": "2025-01-01T00:00:00+00:00", "type": "message",
        "subtype": None, "thread_ts": None, "reactions": None, "reply_count": 0, "raw": {},
    }
    base.update(overrides)
    return base


class TestNdjsonBackend:
    def test_store_messages_in_channel_dir(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        messages = [_make_msg(ts="100.0", text="hello"), _make_msg(ts="101.0", text="world")]

        count = backend.store_messages("C1", "general", messages)
        assert count == 2

        path = tmp_path / "out" / "general" / "messages.ndjson"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "hello"
        assert json.loads(lines[1])["text"] == "world"

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
