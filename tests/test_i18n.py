"""Unicode round-trip tests — Slack text and filenames may be Japanese / Vietnamese."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from slack_sync.storage.ndjson import NdjsonBackend
from slack_sync.files import FileDownloader

JP = "会議の議事録です。よろしくお願いします。"
VN = "Đây là biên bản cuộc họp. Trân trọng cảm ơn các bạn nhé!"
MIXED = f"{JP} / {VN}"


def _msg(text, file_name=None):
    raw = {"ts": "100.0", "text": text}
    if file_name:
        raw["files"] = [{
            "id": "F1", "name": file_name, "size": 10, "filetype": "pdf",
            "url_private_download": "https://files.slack.com/x",
        }]
    return {
        "channel_id": "C1", "channel_name": "general", "ts": "100.0",
        "datetime_utc": "2025-01-01T00:00:00+00:00", "user_id": "U1",
        "thread_ts": None, "text": text, "type": "message", "subtype": None,
        "reactions": None, "reply_count": 0, "raw": raw,
    }


class TestUnicodeStorage:
    def test_message_text_roundtrip(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_messages("C1", "general", [_msg(MIXED)])

        line = (tmp_path / "out" / "general" / "messages.ndjson").read_text(encoding="utf-8").strip()
        record = json.loads(line)
        assert record["text"] == MIXED
        # Stored as real UTF-8, not \uXXXX escapes.
        assert JP in line and VN in line

    def test_raw_text_roundtrip(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_messages("C1", "general", [_msg(MIXED)])

        raw_line = (tmp_path / "out" / "general" / "raw.ndjson").read_text(encoding="utf-8").strip()
        assert json.loads(raw_line)["raw"]["text"] == MIXED

    def test_users_roundtrip(self, tmp_path):
        backend = NdjsonBackend(str(tmp_path / "out"))
        backend.store_users({"U1": {"id": "U1", "display_name": "田中太郎",
                                    "real_name": "Nguyễn Văn Anh", "email": None}})
        data = json.loads((tmp_path / "out" / "_users.json").read_text(encoding="utf-8"))
        assert data["U1"]["display_name"] == "田中太郎"
        assert data["U1"]["real_name"] == "Nguyễn Văn Anh"


class TestUnicodeFilenames:
    def test_sanitize_preserves_unicode(self):
        name = "報告書_Báo_cáo_2025.pdf"
        assert FileDownloader._sanitize_filename(name) == name

    def test_sanitize_strips_forbidden_keeps_unicode(self):
        assert FileDownloader._sanitize_filename('日本語<:>ファイル.pdf') == "日本語___ファイル.pdf"

    def test_file_index_text_roundtrip(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        session = MagicMock()
        resp = MagicMock(status_code=200, headers={})
        resp.iter_content.return_value = [b"data"]
        session.get.return_value = resp
        dl._local.session = session

        dl.download_message_files(_msg(MIXED, file_name="議事録_biênbản.pdf"), "general")
        dl.save_file_indexes()

        index = json.loads((tmp_path / "general" / "_files_index.json").read_text(encoding="utf-8"))
        assert index[0]["file_name"] == "議事録_biênbản.pdf"
        assert index[0]["message_text"] == MIXED
        assert (tmp_path / "general" / "files" / "F1_議事録_biênbản.pdf").exists()
