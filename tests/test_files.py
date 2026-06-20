"""Tests for file attachment downloader."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sync.files import FileDownloader


def _mock_session(content=b"data", status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    resp.iter_content.return_value = [content]
    session = MagicMock()
    session.get.return_value = resp
    return session


def _attach_session(dl, session):
    """Inject a mock session into the downloader's thread-local."""
    dl._local.session = session


class TestFileDownloader:
    def _make_msg_with_file(self, file_id="F001", name="report.pdf", url="https://files.slack.com/file1", size=1024):
        return {
            "channel_id": "C1",
            "channel_name": "general",
            "ts": "100.0",
            "datetime_utc": "2025-01-01T00:00:00+00:00",
            "user_id": "U1",
            "thread_ts": None,
            "text": "check this",
            "raw": {
                "files": [{
                    "id": file_id, "name": name, "mimetype": "application/pdf",
                    "url_private_download": url, "size": size, "filetype": "pdf",
                }]
            },
        }

    def test_no_files_returns_empty(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {"channel_id": "C1", "ts": "100.0", "text": "hi", "raw": {}}
        assert dl.download_message_files(msg, "general") == []

    def test_skips_tombstone_files(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {"channel_id": "C1", "ts": "100.0", "text": "", "raw": {
            "files": [{"id": "F001", "name": "deleted.pdf", "mode": "tombstone"}]}}
        assert dl.download_message_files(msg, "general") == []

    def test_skips_file_without_url(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {"channel_id": "C1", "ts": "100.0", "text": "", "raw": {
            "files": [{"id": "F001", "name": "nourl.pdf"}]}}
        assert dl.download_message_files(msg, "general") == []

    def test_skips_oversized_file(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path), max_file_size_mb=1)
        _attach_session(dl, _mock_session())
        msg = self._make_msg_with_file(size=5 * 1024 * 1024)  # 5 MB > 1 MB cap
        assert dl.download_message_files(msg, "general") == []

    def test_downloads_file_successfully(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        _attach_session(dl, _mock_session(content=b"file content here"))
        result = dl.download_message_files(self._make_msg_with_file(), "general")

        assert len(result) == 1
        assert result[0]["file_id"] == "F001"
        downloaded = tmp_path / "general" / "files" / "F001_report.pdf"
        assert downloaded.exists()
        assert downloaded.read_bytes() == b"file content here"

    def test_skips_already_downloaded(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        session = _mock_session()
        _attach_session(dl, session)
        msg = self._make_msg_with_file()

        dl.download_message_files(msg, "general")
        dl.download_message_files(msg, "general")
        assert session.get.call_count == 1

    def test_builds_file_index(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        _attach_session(dl, _mock_session())
        dl.download_message_files(self._make_msg_with_file(), "general")
        dl.save_file_indexes()

        import json
        index = json.loads((tmp_path / "general" / "_files_index.json").read_text())
        assert len(index) == 1
        assert index[0]["sender_user_id"] == "U1"
        assert index[0]["message_ts"] == "100.0"
        assert index[0]["filetype"] == "pdf"


class TestSanitizeFilename:
    def test_removes_forbidden_chars(self):
        assert FileDownloader._sanitize_filename('my<file>:name.pdf') == "my_file__name.pdf"

    def test_empty_becomes_file(self):
        assert FileDownloader._sanitize_filename("...") == "file"

    def test_normal_name_unchanged(self):
        assert FileDownloader._sanitize_filename("report_2025.pdf") == "report_2025.pdf"
