"""Thread reply fetching with pagination."""

from __future__ import annotations

import logging
from typing import Any, Optional

from slack_sync.client import SlackClient
from slack_sync.history import normalize_message

logger = logging.getLogger(__name__)


def fetch_thread_replies(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    thread_ts: str,
    oldest: Optional[str] = None,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Fetch all replies in a thread, excluding the parent message.

    If `oldest` is provided, only replies newer than that ts are returned
    (incremental thread sync).
    """
    replies: list[dict[str, Any]] = []
    cursor: Optional[str] = None

    while True:
        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": page_size,
        }
        if oldest:
            kwargs["oldest"] = oldest
        if cursor:
            kwargs["cursor"] = cursor

        data = client.api_call("conversations_replies", **kwargs)
        batch = data.get("messages", [])

        for msg in batch:
            if msg.get("ts") == thread_ts and msg.get("thread_ts") == thread_ts:
                if not msg.get("parent_user_id"):
                    continue
            replies.append(normalize_message(msg, channel_id, channel_name))

        if not data.get("has_more", False):
            break
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    replies.sort(key=lambda m: m["ts"])
    logger.debug("Thread %s in %s: %d replies fetched.", thread_ts, channel_name, len(replies))
    return replies
