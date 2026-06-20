"""Incremental message history fetch with streaming pagination."""

from __future__ import annotations

import logging
from collections.abc import Iterator
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


def iter_channel_history(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
    page_size: int = 200,
) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of normalized messages, one Slack API page at a time.

    Streaming (rather than collecting everything into one list) keeps peak
    memory bounded to a single page regardless of channel size. Pages are
    returned newest-first within Slack's [oldest, latest] window.
    """
    cursor: Optional[str] = None
    page = 0

    while True:
        kwargs: dict[str, Any] = {"channel": channel_id, "limit": page_size}
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest
        if cursor:
            kwargs["cursor"] = cursor

        data = client.api_call("conversations_history", **kwargs)
        batch = data.get("messages", [])
        page += 1
        logger.debug("Channel %s page %d: fetched %d messages.", channel_name, page, len(batch))

        yield [normalize_message(m, channel_id, channel_name) for m in batch]

        if not data.get("has_more", False):
            break
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break


def fetch_channel_history(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    oldest: Optional[str] = None,
    latest: Optional[str] = None,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Collect all messages into a single sorted list.

    Convenience wrapper over iter_channel_history for callers that need the
    full result at once (e.g. small ad-hoc pulls and tests). The streaming
    sync path uses iter_channel_history directly to bound memory.
    """
    messages: list[dict[str, Any]] = []
    for page in iter_channel_history(client, channel_id, channel_name, oldest, latest, page_size):
        messages.extend(page)
    messages.sort(key=lambda m: m["ts"])
    logger.info("Channel %s: %d messages fetched.", channel_name, len(messages))
    return messages
