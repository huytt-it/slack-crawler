"""Incremental message history fetch with pagination."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from slack_sync.client import SlackClient

logger = logging.getLogger(__name__)


def normalize_message(msg: dict[str, Any], channel_id: str, channel_name: str) -> dict[str, Any]:
    """Transform a raw Slack message into the normalized schema."""
    ts = msg.get("ts", "")
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc) if ts else None

    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "ts": ts,
        "datetime_utc": dt.isoformat() if dt else None,
        "user_id": msg.get("user", msg.get("bot_id", "")),
        "thread_ts": msg.get("thread_ts"),
        "text": msg.get("text", ""),
        "type": msg.get("type", ""),
        "subtype": msg.get("subtype"),
        "reactions": msg.get("reactions"),
        "reply_count": msg.get("reply_count", 0),
        "raw": msg,
    }


def fetch_channel_history(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Fetch all messages in a channel newer than `oldest` and older than `latest`, paginated.

    Returns normalized messages sorted by ts ascending.
    """
    messages: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    page = 0

    while True:
        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "limit": page_size,
        }
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest
        if cursor:
            kwargs["cursor"] = cursor

        data = client.api_call("conversations_history", **kwargs)
        batch = data.get("messages", [])
        page += 1

        for msg in batch:
            messages.append(normalize_message(msg, channel_id, channel_name))

        logger.debug(
            "Channel %s page %d: fetched %d messages.", channel_name, page, len(batch),
        )

        if not data.get("has_more", False):
            break
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    messages.sort(key=lambda m: m["ts"])
    logger.info("Channel %s: %d new messages fetched.", channel_name, len(messages))
    return messages
