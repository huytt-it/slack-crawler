"""Tests for file attachment downloader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from slack_sync.files import FileDownloader


class TestFileDownloader:
    def _make_msg_with_file(self, file_id="F001", name="report.pdf", url="https://files.slack.com/file1"):
        return {
            "channel_id": "C1",
            "ts": "100.0",
            "text": "check this",
            "raw": {
                "files": [
                    {
                        "id": file_id,
                        "name": name,
                        "mimetype": "application/pdf",
                        "url_private_download": url,
                        "size": 1024,
                    }
                ]
            },
        }

    def test_no_files_returns_empty(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {"channel_id": "C1", "ts": "100.0", "text": "hi", "raw": {}}
        result = dl.download_message_files(msg, "general")
        assert result == []

    def test_skips_tombstone_files(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {
            "channel_id": "C1", "ts": "100.0", "text": "", "raw": {
                "files": [{"id": "F001", "name": "deleted.pdf", "mode": "tombstone"}]
            }
        }
        result = dl.download_message_files(msg, "general")
        assert result == []

    def test_skips_file_without_url(self, tmp_path):
        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = {
            "channel_id": "C1", "ts": "100.0", "text": "", "raw": {
                "files": [{"id": "F001", "name": "nourl.pdf"}]
            }
        }
        result = dl.download_message_files(msg, "general")
        assert result == []

    @patch("slack_sync.files.requests.get")
    def test_downloads_file_successfully(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"file content here"]
        mock_get.return_value = mock_resp

        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = self._make_msg_with_file()
        result = dl.download_message_files(msg, "general")

        assert len(result) == 1
        assert result[0]["file_id"] == "F001"
        assert result[0]["name"] == "report.pdf"

        downloaded = tmp_path / "general" / "files" / "F001_report.pdf"
        assert downloaded.exists()
        assert downloaded.read_bytes() == b"file content here"

    @patch("slack_sync.files.requests.get")
    def test_skips_already_downloaded(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"data"]
        mock_get.return_value = mock_resp

        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = self._make_msg_with_file()

        dl.download_message_files(msg, "general")
        dl.download_message_files(msg, "general")

        assert mock_get.call_count == 1

    @patch("slack_sync.files.requests.get")
    def test_creates_channel_files_dir(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"x"]
        mock_get.return_value = mock_resp

        dl = FileDownloader("xoxp-test", str(tmp_path))
        msg = self._make_msg_with_file()
        dl.download_message_files(msg, "engineering")

        assert (tmp_path / "engineering" / "files").is_dir()


class TestSanitizeFilename:
    def test_removes_forbidden_chars(self):
        assert FileDownloader._sanitize_filename('my<file>:name.pdf') == "my_file__name.pdf"

    def test_empty_becomes_file(self):
        assert FileDownloader._sanitize_filename("...") == "file"

    def test_normal_name_unchanged(self):
        assert FileDownloader._sanitize_filename("report_2025.pdf") == "report_2025.pdf"
