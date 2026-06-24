"""Tests for channel discovery and filtering."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sdk.errors import SlackApiError
from slack_sync.channels import discover_channels, Channel


class TestDiscoverChannels:
    def _mock_client(self, channels):
        client = MagicMock()
        client.api_call.return_value = {
            "channels": channels,
            "response_metadata": {"next_cursor": ""},
        }
        return client

    def test_discovers_all_channels(self):
        client = self._mock_client([
            {"id": "C1", "name": "general", "is_private": False},
            {"id": "C2", "name": "random", "is_private": False},
            {"id": "C3", "name": "secret", "is_private": True},
        ])

        result = discover_channels(client)
        assert len(result) == 3
        assert all(isinstance(c, Channel) for c in result)

    def test_allowlist_by_name(self):
        client = self._mock_client([
            {"id": "C1", "name": "general", "is_private": False},
            {"id": "C2", "name": "random", "is_private": False},
            {"id": "C3", "name": "engineering", "is_private": False},
        ])

        result = discover_channels(client, allowlist=["general", "engineering"])
        assert len(result) == 2
        names = {c.name for c in result}
        assert names == {"general", "engineering"}

    def test_allowlist_by_id(self):
        client = self._mock_client([
            {"id": "C1", "name": "general", "is_private": False},
            {"id": "C2", "name": "random", "is_private": False},
        ])

        result = discover_channels(client, allowlist=["C1"])
        assert len(result) == 1
        assert result[0].id == "C1"

    def test_denylist_by_name(self):
        client = self._mock_client([
            {"id": "C1", "name": "general", "is_private": False},
            {"id": "C2", "name": "random", "is_private": False},
            {"id": "C3", "name": "social", "is_private": False},
        ])

        result = discover_channels(client, denylist=["random", "social"])
        assert len(result) == 1
        assert result[0].name == "general"

    def test_allowlist_and_denylist_combined(self):
        client = self._mock_client([
            {"id": "C1", "name": "general", "is_private": False},
            {"id": "C2", "name": "random", "is_private": False},
            {"id": "C3", "name": "engineering", "is_private": False},
        ])

        result = discover_channels(
            client,
            allowlist=["general", "random", "engineering"],
            denylist=["random"],
        )
        assert len(result) == 2
        names = {c.name for c in result}
        assert "random" not in names

    def test_types_passed_to_api(self):
        client = self._mock_client([{"id": "C1", "name": "general", "is_private": False}])
        discover_channels(client, types="public_channel")
        assert client.api_call.call_args[1]["types"] == "public_channel"

    def test_falls_back_to_public_on_missing_scope(self):
        resp = MagicMock()
        resp.get.return_value = "missing_scope"

        def side_effect(method, **kwargs):
            if "private_channel" in kwargs.get("types", ""):
                raise SlackApiError("missing_scope", resp)
            return {"channels": [{"id": "C1", "name": "general", "is_private": False}],
                    "response_metadata": {"next_cursor": ""}}

        client = MagicMock()
        client.api_call.side_effect = side_effect

        result = discover_channels(client, types="public_channel,private_channel")
        assert len(result) == 1
        assert result[0].name == "general"

    def test_missing_scope_on_public_reraises(self):
        resp = MagicMock()
        resp.get.return_value = "missing_scope"
        client = MagicMock()
        client.api_call.side_effect = SlackApiError("missing_scope", resp)

        import pytest
        with pytest.raises(SlackApiError):
            discover_channels(client, types="public_channel")
