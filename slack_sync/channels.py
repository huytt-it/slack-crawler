"""Channel discovery and filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from slack_sdk.errors import SlackApiError

from slack_sync.client import SlackClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    is_private: bool


def _list_conversations(client: SlackClient, types: str) -> list[Channel]:
    """Paginate users.conversations for the given comma-separated types."""
    channels: list[Channel] = []
    cursor: Optional[str] = None

    while True:
        kwargs: dict = {
            "types": types,
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

    return channels


def discover_channels(
    client: SlackClient,
    allowlist: Optional[list[str]] = None,
    denylist: Optional[list[str]] = None,
    types: str = "public_channel",
) -> list[Channel]:
    """Fetch the channels the token's identity is a member of, then apply filters.

    `types` is a comma-separated list of Slack conversation types
    (public_channel, private_channel, mpim, im). If the token lacks the scope
    for a requested type (e.g. private_channel without groups:read), discovery
    degrades gracefully to public_channel instead of crashing.

    Allowlist/denylist entries can be channel IDs or names. Allowlist (if set)
    is applied first, then denylist removes matches.
    """
    try:
        channels = _list_conversations(client, types)
    except SlackApiError as e:
        error = e.response.get("error", "") if e.response else ""
        if error == "missing_scope" and types != "public_channel":
            logger.warning(
                "Token is missing scope for requested types '%s'. "
                "Falling back to public_channel only (add groups:read for private channels).",
                types,
            )
            channels = _list_conversations(client, "public_channel")
        else:
            raise

    logger.info("Discovered %d channels (types=%s) before filtering.", len(channels), types)

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
