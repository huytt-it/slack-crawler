"""User resolution with per-run caching and pseudonymization hook."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from slack_sync.client import SlackClient

logger = logging.getLogger(__name__)


@dataclass
class UserInfo:
    id: str
    display_name: str
    real_name: str
    email: Optional[str] = None


class UserResolver:
    """Fetches and caches the full user list once per sync run."""

    def __init__(self, client: SlackClient, pseudonymize: bool = False) -> None:
        self._client = client
        self._pseudonymize = pseudonymize
        self._cache: dict[str, UserInfo] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return

        cursor: Optional[str] = None
        while True:
            kwargs: dict = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            data = self._client.api_call("users_list", **kwargs)
            for member in data.get("members", []):
                profile = member.get("profile", {})
                self._cache[member["id"]] = UserInfo(
                    id=member["id"],
                    display_name=profile.get("display_name", ""),
                    real_name=profile.get("real_name", member.get("real_name", "")),
                    email=profile.get("email"),
                )

            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        logger.info("Cached %d users.", len(self._cache))
        self._loaded = True

    def resolve(self, user_id: str) -> UserInfo:
        self._load()
        if user_id in self._cache:
            info = self._cache[user_id]
            if self._pseudonymize:
                return self._pseudonymize_user(info)
            return info
        return UserInfo(id=user_id, display_name=user_id, real_name=user_id)

    def get_all(self) -> dict[str, UserInfo]:
        self._load()
        if self._pseudonymize:
            return {uid: self._pseudonymize_user(info) for uid, info in self._cache.items()}
        return dict(self._cache)

    @staticmethod
    def _pseudonymize_user(info: UserInfo) -> UserInfo:
        """Replace identifying fields with a stable hash-based synthetic ID."""
        seed = info.email or info.id
        synthetic = "user_" + hashlib.sha256(seed.encode()).hexdigest()[:12]
        return UserInfo(
            id=info.id,
            display_name=synthetic,
            real_name=synthetic,
            email=None,
        )
