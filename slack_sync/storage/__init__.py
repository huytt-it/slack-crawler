"""Pluggable storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Interface for message persistence backends."""

    @abstractmethod
    def store_messages(self, channel_id: str, channel_name: str, messages: list[dict[str, Any]]) -> int:
        """Persist a batch of normalized messages. Returns the count stored."""

    @abstractmethod
    def store_users(self, users: dict[str, dict[str, Any]]) -> None:
        """Persist the user mapping."""

    @abstractmethod
    def close(self) -> None:
        """Release any resources."""
