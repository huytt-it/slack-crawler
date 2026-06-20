"""CLI entry point for Slack incremental sync."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from slack_sync.channels import discover_channels
from slack_sync.client import SlackClient
from slack_sync.config import Config, load_config
from slack_sync.history import fetch_channel_history
from slack_sync.state import WatermarkStore
from slack_sync.storage import StorageBackend
from slack_sync.storage.ndjson import NdjsonBackend
from slack_sync.threads import fetch_thread_replies
from slack_sync.users import UserResolver

logger = logging.getLogger("slack_sync")


def build_storage(config: Config) -> StorageBackend:
    if config.output_mode == "postgres":
        from slack_sync.storage.postgres import PostgresBackend
        return PostgresBackend(config.db_connection_string)  # type: ignore[arg-type]
    return NdjsonBackend(config.output_dir)


def _date_to_ts(date_str: str) -> str:
    """Convert YYYY-MM-DD to a Slack-compatible Unix timestamp string."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(dt.timestamp())


def sync_channel(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    watermark_store: WatermarkStore,
    storage: StorageBackend,
    config: Config,
) -> int:
    """Sync a single channel incrementally. Returns total messages stored."""
    if config.since:
        oldest = _date_to_ts(config.since)
        logger.info("Channel %s: using --since %s as start date.", channel_name, config.since)
    elif (existing_wm := watermark_store.get(channel_id)):
        oldest = existing_wm
        logger.info("Channel %s: resuming from watermark %s.", channel_name, oldest)
    else:
        lookback = datetime.now(timezone.utc) - timedelta(days=config.lookback_days)
        oldest = str(lookback.timestamp())
        logger.info("Channel %s: first run, looking back %d days.", channel_name, config.lookback_days)

    latest = _date_to_ts(config.until) if config.until else None
    if latest:
        logger.info("Channel %s: using --until %s as end date.", channel_name, config.until)

    messages = fetch_channel_history(
        client, channel_id, channel_name,
        oldest=oldest, latest=latest, page_size=config.page_size,
    )

    if not messages:
        logger.info("Channel %s: no new messages.", channel_name)
        return 0

    thread_replies: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("reply_count", 0) > 0 and msg.get("thread_ts"):
            replies = fetch_thread_replies(
                client, channel_id, channel_name,
                thread_ts=msg["thread_ts"],
                oldest=oldest,
                page_size=config.thread_page_size,
            )
            thread_replies.extend(replies)

    all_messages = messages + thread_replies
    seen: set[tuple[str, str]] = set()
    deduplicated: list[dict[str, Any]] = []
    for msg in all_messages:
        key = (msg["channel_id"], msg["ts"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(msg)
    deduplicated.sort(key=lambda m: m["ts"])

    stored = storage.store_messages(channel_id, channel_name, deduplicated)

    max_ts = max(m["ts"] for m in deduplicated)
    watermark_store.set(channel_id, max_ts)

    return stored


def run(config: Config) -> None:
    """Execute the full sync pipeline."""
    start = time.monotonic()
    client = SlackClient(token=config.slack_token, max_retries=config.max_retries)
    watermark_store = WatermarkStore(config.state_dir)
    storage = build_storage(config)

    try:
        channels = discover_channels(
            client,
            allowlist=config.channel_allowlist or None,
            denylist=config.channel_denylist or None,
        )

        user_resolver = UserResolver(client, pseudonymize=config.pseudonymize)
        all_users = user_resolver.get_all()
        user_dicts = {uid: asdict(info) for uid, info in all_users.items()}
        storage.store_users(user_dicts)

        total = 0
        for ch in channels:
            try:
                count = sync_channel(client, ch.id, ch.name, watermark_store, storage, config)
                total += count
            except Exception:
                logger.exception("Failed to sync channel %s (%s). Continuing.", ch.name, ch.id)

        elapsed = time.monotonic() - start
        logger.info(
            "Sync complete. %d channels processed, %d messages stored in %.1fs.",
            len(channels), total, elapsed,
        )
    finally:
        storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Slack incremental sync tool")
    parser.add_argument("-c", "--config", help="Path to config YAML file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--since", help="Start date (YYYY-MM-DD). Overrides watermark and lookback_days.")
    parser.add_argument("--until", help="End date (YYYY-MM-DD). Only fetch messages before this date.")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (ValueError, FileNotFoundError) as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    if args.since or args.until:
        overrides: dict = {}
        if args.since:
            overrides["since"] = args.since
        if args.until:
            overrides["until"] = args.until
        from dataclasses import replace
        config = replace(config, **overrides)

    run(config)


if __name__ == "__main__":
    main()
