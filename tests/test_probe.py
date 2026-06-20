"""Tests for the pre-flight probe estimator."""

from __future__ import annotations

from unittest.mock import MagicMock
from slack_sync.channels import Channel
from slack_sync.probe import probe_channel


def _channel():
    return Channel(id="C1", name="general", is_private=False)


def test_small_channel_exact_count():
    client = MagicMock()
    client.api_call.return_value = {
        "messages": [{"ts": "100.0"}, {"ts": "101.0"}],
        "has_more": False,
    }
    est = probe_channel(client, _channel(), oldest="50.0", latest=None)
    assert est.has_more is False
    assert est.est_messages == 2


def test_extrapolates_when_has_more():
    # 200 msgs spanning 100s; window is 1000s -> ~10x extrapolation
    msgs = [{"ts": str(1000.0 - i * 0.5)} for i in range(200)]
    client = MagicMock()
    client.api_call.return_value = {"messages": msgs, "has_more": True}
    est = probe_channel(client, _channel(), oldest="0.0", latest=None)
    assert est.has_more is True
    assert est.est_messages > 200


def test_counts_files_and_bytes():
    msgs = [
        {"ts": "100.0", "files": [{"size": 1000}]},
        {"ts": "101.0", "files": [{"size": 2000}]},
    ]
    client = MagicMock()
    client.api_call.return_value = {"messages": msgs, "has_more": False}
    est = probe_channel(client, _channel(), oldest="50.0", latest=None)
    assert est.est_files == 2
    assert est.est_file_bytes == 3000
