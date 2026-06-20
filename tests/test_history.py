"""Tests for message normalization and history fetch logic."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sync.history import normalize_message, fetch_channel_history


class TestNormalizeMessage:
    def test_basic_message(self):
        raw = {
            "ts": "1700000000.000100",
            "user": "U123",
            "text": "hello world",
            "type": "message",
        }
        result = normalize_message(raw, "C001", "general")

        assert result["channel_id"] == "C001"
        assert result["channel_name"] == "general"
        assert result["ts"] == "1700000000.000100"
        assert result["user_id"] == "U123"
        assert result["text"] == "hello world"
        assert result["type"] == "message"
        assert result["subtype"] is None
        assert result["thread_ts"] is None
        assert result["reactions"] is None
        assert result["reply_count"] == 0
        assert result["raw"] is raw
        assert result["datetime_utc"] is not None

    def test_thread_message(self):
        raw = {
            "ts": "1700000001.000200",
            "user": "U456",
            "text": "reply",
            "type": "message",
            "thread_ts": "1700000000.000100",
            "reply_count": 3,
        }
        result = normalize_message(raw, "C001", "general")
        assert result["thread_ts"] == "1700000000.000100"
        assert result["reply_count"] == 3

    def test_bot_message(self):
        raw = {
            "ts": "1700000002.000300",
            "bot_id": "B789",
            "text": "bot says hi",
            "type": "message",
            "subtype": "bot_message",
        }
        result = normalize_message(raw, "C001", "general")
        assert result["user_id"] == "B789"
        assert result["subtype"] == "bot_message"

    def test_message_with_reactions(self):
        raw = {
            "ts": "1700000003.000400",
            "user": "U123",
            "text": "nice",
            "type": "message",
            "reactions": [{"name": "thumbsup", "count": 2}],
        }
        result = normalize_message(raw, "C001", "general")
        assert result["reactions"] == [{"name": "thumbsup", "count": 2}]

    def test_empty_ts(self):
        raw = {"ts": "", "user": "U123", "text": "x", "type": "message"}
        result = normalize_message(raw, "C001", "general")
        assert result["datetime_utc"] is None


class TestFetchChannelHistory:
    def test_single_page(self):
        client = MagicMock()
        client.api_call.return_value = {
            "messages": [
                {"ts": "1700000001.000100", "user": "U1", "text": "msg1", "type": "message"},
                {"ts": "1700000002.000200", "user": "U2", "text": "msg2", "type": "message"},
            ],
            "has_more": False,
        }

        msgs = fetch_channel_history(client, "C001", "general", oldest="1700000000.000000")
        assert len(msgs) == 2
        assert msgs[0]["ts"] < msgs[1]["ts"]
        client.api_call.assert_called_once()

    def test_multiple_pages(self):
        client = MagicMock()
        client.api_call.side_effect = [
            {
                "messages": [{"ts": "1700000001.000100", "user": "U1", "text": "p1", "type": "message"}],
                "has_more": True,
                "response_metadata": {"next_cursor": "cursor_abc"},
            },
            {
                "messages": [{"ts": "1700000002.000200", "user": "U2", "text": "p2", "type": "message"}],
                "has_more": False,
            },
        ]

        msgs = fetch_channel_history(client, "C001", "general")
        assert len(msgs) == 2
        assert client.api_call.call_count == 2

    def test_empty_channel(self):
        client = MagicMock()
        client.api_call.return_value = {"messages": [], "has_more": False}

        msgs = fetch_channel_history(client, "C001", "empty-channel")
        assert msgs == []

    def test_latest_param_passed(self):
        client = MagicMock()
        client.api_call.return_value = {"messages": [], "has_more": False}

        fetch_channel_history(client, "C001", "general", oldest="100", latest="200")
        kwargs = client.api_call.call_args[1]
        assert kwargs["oldest"] == "100"
        assert kwargs["latest"] == "200"
