"""Channel discovery and filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from slack_sync.client import SlackClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    is_private: bool


def discover_channels(
    client: SlackClient,
    allowlist: Optional[list[str]] = None,
    denylist: Optional[list[str]] = None,
) -> list[Channel]:
    """Fetch all channels the token's identity is a member of, then apply filters.

    Allowlist/denylist entries can be channel IDs or channel names.
    If allowlist is non-empty, only those channels are included.
    Denylist is always applied after allowlist.
    """
    channels: list[Channel] = []
    cursor: Optional[str] = None

    while True:
        kwargs: dict = {
            "types": "public_channel,private_channel",
            "exclude_archived": True,
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor

        data = client.api_call("users_conversations", **kwargs)
        for ch in data.get("channels", []):
            channels.append(Channel(
                id=ch["id"],
                name=ch.get("name", ch["id"]),
                is_private=ch.get("is_private", False),
            ))

        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    logger.info("Discovered %d channels before filtering.", len(channels))

    if allowlist:
        allow_set = set(allowlist)
        channels = [c for c in channels if c.id in allow_set or c.name in allow_set]
        logger.info("After allowlist: %d channels.", len(channels))

    if denylist:
        deny_set = set(denylist)
        channels = [c for c in channels if c.id not in deny_set and c.name not in deny_set]
        logger.info("After denylist: %d channels.", len(channels))

    logger.info("Will sync %d channels: %s", len(channels), [c.name for c in channels])
    return channels
