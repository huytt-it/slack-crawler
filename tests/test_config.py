"""Tests for configuration loading and validation."""

from __future__ import annotations

import os
import pytest
from slack_sync.config import Config, load_config


class TestConfigValidation:
    def test_missing_token_raises(self):
        with pytest.raises(ValueError, match="SLACK_TOKEN is required"):
            Config(slack_token="")

    def test_invalid_output_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid output_mode"):
            Config(slack_token="xoxp-test", output_mode="sqlite")

    def test_postgres_without_connection_string_raises(self):
        with pytest.raises(ValueError, match="DB_CONNECTION_STRING is required"):
            Config(slack_token="xoxp-test", output_mode="postgres")

    def test_valid_config(self):
        cfg = Config(slack_token="xoxp-test")
        assert cfg.output_mode == "ndjson"
        assert cfg.lookback_days == 90
        assert cfg.page_size == 200
        assert cfg.since is None
        assert cfg.until is None

    def test_postgres_with_connection_string(self):
        cfg = Config(
            slack_token="xoxp-test",
            output_mode="postgres",
            db_connection_string="postgresql://localhost/test",
        )
        assert cfg.output_mode == "postgres"

    def test_invalid_since_format_raises(self):
        with pytest.raises(ValueError, match="since must be YYYY-MM-DD"):
            Config(slack_token="xoxp-test", since="Jan 1 2025")

    def test_invalid_until_format_raises(self):
        with pytest.raises(ValueError, match="until must be YYYY-MM-DD"):
            Config(slack_token="xoxp-test", until="2025/06/30")

    def test_valid_date_range(self):
        cfg = Config(slack_token="xoxp-test", since="2025-01-01", until="2025-06-30")
        assert cfg.since == "2025-01-01"
        assert cfg.until == "2025-06-30"


class TestLoadConfig:
    def test_load_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SLACK_TOKEN", "xoxp-from-env")
        monkeypatch.setenv("OUTPUT_MODE", "ndjson")
        monkeypatch.setenv("LOOKBACK_DAYS", "30")
        monkeypatch.setenv("PSEUDONYMIZE", "true")
        monkeypatch.setenv("SYNC_SINCE", "2025-03-01")

        cfg = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
        assert cfg.slack_token == "xoxp-from-env"
        assert cfg.lookback_days == 30
        assert cfg.pseudonymize is True
        assert cfg.since == "2025-03-01"

    def test_load_from_yaml(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SLACK_TOKEN", raising=False)
        monkeypatch.delenv("SYNC_SINCE", raising=False)
        monkeypatch.delenv("SYNC_UNTIL", raising=False)

        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "slack_token: xoxp-from-yaml\nlookback_days: 7\nsince: '2025-02-01'\n"
        )
        cfg = load_config(config_path=str(yaml_path))
        assert cfg.slack_token == "xoxp-from-yaml"
        assert cfg.lookback_days == 7
        assert cfg.since == "2025-02-01"

    def test_env_overrides_yaml(self, monkeypatch, tmp_path):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text("slack_token: xoxp-yaml\nlookback_days: 7\n")

        monkeypatch.setenv("SLACK_TOKEN", "xoxp-env-wins")
        monkeypatch.setenv("LOOKBACK_DAYS", "180")

        cfg = load_config(config_path=str(yaml_path))
        assert cfg.slack_token == "xoxp-env-wins"
        assert cfg.lookback_days == 180

    def test_channel_list_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SLACK_TOKEN", "xoxp-test")
        monkeypatch.setenv("CHANNEL_ALLOWLIST", "general, engineering, random")
        monkeypatch.setenv("CHANNEL_DENYLIST", "social")

        cfg = load_config(config_path=str(tmp_path / "none.yaml"))
        assert cfg.channel_allowlist == ["general", "engineering", "random"]
        assert cfg.channel_denylist == ["social"]
