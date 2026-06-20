"""Tests for user resolution and pseudonymization."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sync.users import UserResolver, UserInfo


class TestUserResolver:
    def _mock_client(self, members):
        client = MagicMock()
        client.api_call.return_value = {
            "members": members,
            "response_metadata": {"next_cursor": ""},
        }
        return client

    def test_resolve_known_user(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice", "email": "alice@co.com"}},
        ])

        resolver = UserResolver(client)
        user = resolver.resolve("U1")
        assert user.display_name == "alice"
        assert user.real_name == "Alice"
        assert user.email == "alice@co.com"

    def test_resolve_unknown_user(self):
        client = self._mock_client([])

        resolver = UserResolver(client)
        user = resolver.resolve("U_UNKNOWN")
        assert user.id == "U_UNKNOWN"
        assert user.display_name == "U_UNKNOWN"

    def test_get_all(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice"}},
            {"id": "U2", "real_name": "Bob", "profile": {"display_name": "bob", "real_name": "Bob"}},
        ])

        resolver = UserResolver(client)
        all_users = resolver.get_all()
        assert len(all_users) == 2
        assert "U1" in all_users
        assert "U2" in all_users

    def test_caches_across_calls(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice"}},
        ])

        resolver = UserResolver(client)
        resolver.resolve("U1")
        resolver.resolve("U1")
        assert client.api_call.call_count == 1


class TestPseudonymization:
    def _mock_client(self, members):
        client = MagicMock()
        client.api_call.return_value = {
            "members": members,
            "response_metadata": {"next_cursor": ""},
        }
        return client

    def test_pseudonymize_replaces_names(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice", "email": "alice@co.com"}},
        ])

        resolver = UserResolver(client, pseudonymize=True)
        user = resolver.resolve("U1")
        assert user.display_name.startswith("user_")
        assert user.real_name.startswith("user_")
        assert user.email is None
        assert user.display_name != "alice"

    def test_pseudonymize_is_stable(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice", "email": "alice@co.com"}},
        ])

        resolver = UserResolver(client, pseudonymize=True)
        user1 = resolver.resolve("U1")
        user2 = resolver.resolve("U1")
        assert user1.display_name == user2.display_name

    def test_pseudonymize_different_emails_differ(self):
        client = self._mock_client([
            {"id": "U1", "real_name": "Alice", "profile": {"display_name": "alice", "real_name": "Alice", "email": "alice@co.com"}},
            {"id": "U2", "real_name": "Bob", "profile": {"display_name": "bob", "real_name": "Bob", "email": "bob@co.com"}},
        ])

        resolver = UserResolver(client, pseudonymize=True)
        u1 = resolver.resolve("U1")
        u2 = resolver.resolve("U2")
        assert u1.display_name != u2.display_name
