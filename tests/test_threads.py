"""Tests for thread reply fetching."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sync.threads import fetch_thread_replies


class TestFetchThreadReplies:
    def test_skips_parent_message(self):
        client = MagicMock()
        client.api_call.return_value = {
            "messages": [
                {"ts": "1700000000.000100", "thread_ts": "1700000000.000100",
                 "user": "U1", "text": "parent", "type": "message"},
                {"ts": "1700000001.000200", "thread_ts": "1700000000.000100",
                 "user": "U2", "text": "reply1", "type": "message", "parent_user_id": "U1"},
                {"ts": "1700000002.000300", "thread_ts": "1700000000.000100",
                 "user": "U3", "text": "reply2", "type": "message", "parent_user_id": "U1"},
            ],
            "has_more": False,
        }

        replies = fetch_thread_replies(client, "C001", "general", "1700000000.000100")
        assert len(replies) == 2
        assert all(r["text"] != "parent" for r in replies)

    def test_empty_thread(self):
        client = MagicMock()
        client.api_call.return_value = {"messages": [], "has_more": False}

        replies = fetch_thread_replies(client, "C001", "general", "1700000000.000100")
        assert replies == []

    def test_paginated_replies(self):
        client = MagicMock()
        client.api_call.side_effect = [
            {
                "messages": [
                    {"ts": "1700000001.000200", "thread_ts": "1700000000.000100",
                     "user": "U2", "text": "r1", "type": "message", "parent_user_id": "U1"},
                ],
                "has_more": True,
                "response_metadata": {"next_cursor": "cur1"},
            },
            {
                "messages": [
                    {"ts": "1700000002.000300", "thread_ts": "1700000000.000100",
                     "user": "U3", "text": "r2", "type": "message", "parent_user_id": "U1"},
                ],
                "has_more": False,
            },
        ]

        replies = fetch_thread_replies(client, "C001", "general", "1700000000.000100")
        assert len(replies) == 2
        assert client.api_call.call_count == 2
