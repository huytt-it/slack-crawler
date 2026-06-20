"""Configuration loading from environment variables and optional YAML file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class Config:
    slack_token: str
    output_mode: str = "ndjson"  # "ndjson" or "postgres"
    db_connection_string: Optional[str] = None
    output_dir: str = "output"
    state_dir: str = ".state"
    channel_allowlist: list[str] = field(default_factory=list)
    channel_denylist: list[str] = field(default_factory=list)
    lookback_days: int = 90
    page_size: int = 200
    thread_page_size: int = 200
    max_retries: int = 5
    pseudonymize: bool = False
    since: Optional[str] = None  # ISO date, e.g. "2025-01-01"
    until: Optional[str] = None  # ISO date, e.g. "2025-06-30"

    def __post_init__(self) -> None:
        if not self.slack_token:
            raise ValueError("SLACK_TOKEN is required")
        if self.output_mode not in ("ndjson", "postgres"):
            raise ValueError(f"Invalid output_mode: {self.output_mode}")
        if self.output_mode == "postgres" and not self.db_connection_string:
            raise ValueError("DB_CONNECTION_STRING is required for postgres output mode")
        for field_name in ("since", "until"):
            val = getattr(self, field_name)
            if val:
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    raise ValueError(f"{field_name} must be YYYY-MM-DD format, got: {val}")


def load_config(config_path: Optional[str] = None) -> Config:
    """Load config by merging YAML file (if present) with environment variables.

    Env vars take precedence over YAML values.
    """
    file_values: dict = {}

    if config_path is None:
        for candidate in ("config.yaml", "config.yml"):
            if Path(candidate).is_file():
                config_path = candidate
                break

    if config_path and Path(config_path).is_file():
        with open(config_path, "r", encoding="utf-8") as f:
            file_values = yaml.safe_load(f) or {}

    def _get(key: str, default=None, yaml_key: str | None = None):
        env_val = os.environ.get(key.upper())
        if env_val is not None:
            return env_val
        return file_values.get(yaml_key or key.lower(), default)

    def _get_list(key: str) -> list[str]:
        env_val = os.environ.get(key.upper(), "")
        if env_val:
            return [s.strip() for s in env_val.split(",") if s.strip()]
        file_val = file_values.get(key.lower(), [])
        if isinstance(file_val, str):
            return [s.strip() for s in file_val.split(",") if s.strip()]
        return list(file_val) if file_val else []

    token = _get("SLACK_TOKEN", "")

    return Config(
        slack_token=token,
        output_mode=_get("OUTPUT_MODE", "ndjson"),
        db_connection_string=_get("DB_CONNECTION_STRING"),
        output_dir=_get("OUTPUT_DIR", "output"),
        state_dir=_get("STATE_DIR", ".state"),
        channel_allowlist=_get_list("CHANNEL_ALLOWLIST"),
        channel_denylist=_get_list("CHANNEL_DENYLIST"),
        lookback_days=int(_get("LOOKBACK_DAYS", 90)),
        page_size=int(_get("PAGE_SIZE", 200)),
        thread_page_size=int(_get("THREAD_PAGE_SIZE", 200)),
        max_retries=int(_get("MAX_RETRIES", 5)),
        pseudonymize=str(_get("PSEUDONYMIZE", "false")).lower() in ("true", "1", "yes"),
        since=_get("SYNC_SINCE", yaml_key="since"),
        until=_get("SYNC_UNTIL", yaml_key="until"),
    )
