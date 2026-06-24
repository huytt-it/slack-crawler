"""CLI entry point for Slack incremental sync."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from slack_sync.channels import discover_channels
from slack_sync.client import SlackClient
from slack_sync.config import Config, load_config
from slack_sync.files import FileDownloader
from slack_sync.history import iter_channel_history
from slack_sync.probe import probe_channel, print_report
from slack_sync.ratelimit import PerMethodRateLimiter
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
    return NdjsonBackend(config.output_dir, store_raw=config.store_raw)


def _date_to_ts(date_str: str) -> str:
    """Convert YYYY-MM-DD to a Slack-compatible Unix timestamp string."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return str(dt.timestamp())


def _resolve_bounds(config: Config, watermark_store: WatermarkStore, channel_id: str) -> tuple[str, Optional[str]]:
    """Resolve the [oldest, latest] timestamps for a channel run."""
    if config.since:
        oldest = _date_to_ts(config.since)
    elif config.use_watermark and (wm := watermark_store.get(channel_id)):
        oldest = wm
    else:
        oldest = str((datetime.now(timezone.utc) - timedelta(days=config.lookback_days)).timestamp())
    latest = _date_to_ts(config.until) if config.until else None
    return oldest, latest


def sync_channel(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    watermark_store: WatermarkStore,
    storage: StorageBackend,
    config: Config,
    file_downloader: FileDownloader | None,
    now_ts: str,
) -> int:
    """Stream a channel page-by-page, checkpointing after each page."""
    oldest_bound, latest_bound = _resolve_bounds(config, watermark_store, channel_id)
    plan = watermark_store.plan_run(channel_id, oldest_bound, latest_bound, config.use_watermark)

    high = plan.high_start
    total = 0

    for page in iter_channel_history(
        client, channel_id, channel_name,
        oldest=plan.oldest, latest=plan.latest, page_size=config.page_size,
    ):
        if not page:
            continue

        page_min = min(page, key=lambda m: float(m["ts"]))["ts"]
        page_max = max(page, key=lambda m: float(m["ts"]))["ts"]

        thread_replies: list[dict[str, Any]] = []
        for msg in page:
            if msg.get("reply_count", 0) > 0 and msg.get("thread_ts"):
                thread_replies.extend(fetch_thread_replies(
                    client, channel_id, channel_name,
                    thread_ts=msg["thread_ts"],
                    oldest=plan.oldest,
                    page_size=config.thread_page_size,
                ))

        batch = page + thread_replies
        if thread_replies:
            reply_max = max(thread_replies, key=lambda m: float(m["ts"]))["ts"]
            if float(reply_max) > float(page_max):
                page_max = reply_max

        if file_downloader:
            file_downloader.process_page_files(batch, channel_name)

        storage.store_messages(channel_id, channel_name, batch)
        total += len(batch)

        if float(page_max) > float(high or "0"):
            high = page_max
        watermark_store.checkpoint(channel_id, low=page_min, high=high)

    watermark_store.complete(channel_id, high, config.use_watermark, wrote_any=total > 0, now_ts=now_ts)
    if file_downloader:
        file_downloader._flush_channel(channel_name.replace("/", "_").replace("\\", "_"))

    if total == 0:
        logger.info("Channel %s: no new messages.", channel_name)
    else:
        logger.info("Channel %s: %d messages stored.", channel_name, total)
    return total


def _token_kind(token: str) -> str:
    if token.startswith("xoxb-"):
        return "bot token (xoxb-...)"
    if token.startswith("xoxp-"):
        return "user token (xoxp-...)"
    return "token set"


def _log_config(config: Config, dry_run: bool) -> None:
    """Print the effective configuration (never the token or collected data)."""
    logger.info("=" * 52)
    logger.info("SlackCrawler%s", "  [DRY RUN]" if dry_run else "")
    logger.info("  token         : %s", _token_kind(config.slack_token))
    dest = config.output_dir if config.output_mode == "ndjson" else "(postgres)"
    logger.info("  output        : %s -> %s", config.output_mode, dest)
    logger.info("  channel types : %s", config.channel_types)
    if config.channel_allowlist:
        logger.info("  allowlist     : %s", ",".join(config.channel_allowlist))
    if config.channel_denylist:
        logger.info("  denylist      : %s", ",".join(config.channel_denylist))
    if config.since or config.until:
        logger.info("  range         : since=%s until=%s", config.since or "-", config.until or "now")
    elif config.use_watermark:
        logger.info("  range         : incremental (watermark); first-run lookback %dd", config.lookback_days)
    else:
        logger.info("  range         : lookback %dd (watermark off)", config.lookback_days)
    logger.info("  download files: %s", "yes" if config.download_files else "no")
    logger.info("  store raw     : %s", "yes" if config.store_raw else "no")
    logger.info("  concurrency   : %d ch / %d file | page_size %d | api %.1f/s",
                config.max_workers, config.file_workers, config.page_size, config.api_rate_per_sec)
    logger.info("=" * 52)


def run(config: Config, dry_run: bool = False) -> None:
    """Execute the full sync pipeline."""
    start = time.monotonic()
    now_ts = str(datetime.now(timezone.utc).timestamp())
    _log_config(config, dry_run)
    rate_limiter = PerMethodRateLimiter(config.api_rate_per_sec, burst=max(2, config.max_workers))
    client = SlackClient(config.slack_token, max_retries=config.max_retries, rate_limiter=rate_limiter)
    watermark_store = WatermarkStore(config.state_dir)

    channels = discover_channels(
        client,
        allowlist=config.channel_allowlist or None,
        denylist=config.channel_denylist or None,
        types=config.channel_types,
    )
    if not channels:
        logger.warning("No channels to sync.")
        return

    if dry_run:
        estimates = []
        for ch in channels:
            oldest, latest = _resolve_bounds(config, watermark_store, ch.id)
            try:
                estimates.append(probe_channel(client, ch, oldest, latest, config.page_size))
            except Exception:
                logger.exception("Probe failed for %s.", ch.name)
        print_report(estimates, config.output_dir, config.page_size,
                     config.api_rate_per_sec, config.download_files)
        return

    storage = build_storage(config)
    file_downloader: FileDownloader | None = None
    if config.download_files:
        file_downloader = FileDownloader(
            token=config.slack_token,
            output_dir=config.output_dir,
            max_retries=config.max_retries,
            max_file_size_mb=config.max_file_size_mb,
            workers=config.file_workers,
        )

    try:
        user_resolver = UserResolver(client, pseudonymize=config.pseudonymize)
        user_dicts = {uid: asdict(info) for uid, info in user_resolver.get_all().items()}
        storage.store_users(user_dicts)

        workers = max(1, min(config.max_workers, len(channels)))
        logger.info("Syncing %d channels with %d worker(s)...", len(channels), workers)

        results: dict[str, int | None] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    sync_channel, client, ch.id, ch.name,
                    watermark_store, storage, config, file_downloader, now_ts,
                ): ch
                for ch in channels
            }
            for fut in as_completed(futures):
                ch = futures[fut]
                done += 1
                try:
                    results[ch.name] = fut.result()
                except Exception:
                    logger.exception("[%d/%d] channel %s (%s) FAILED. Continuing.",
                                     done, len(channels), ch.name, ch.id)
                    results[ch.name] = None

        if file_downloader:
            file_downloader.save_file_indexes()

        elapsed = time.monotonic() - start
        ok = sum(1 for v in results.values() if v is not None)
        failed = sum(1 for v in results.values() if v is None)
        total = sum(v for v in results.values() if v)

        logger.info("-" * 52)
        for name, cnt in sorted(results.items()):
            status = f"{cnt:>9,} msgs" if cnt is not None else "    FAILED"
            logger.info("  %-30s %s", name[:30], status)
        logger.info("-" * 52)
        extra = f" | {file_downloader.downloaded_count:,} files" if file_downloader else ""
        logger.info(
            "Done: %d channels (%d ok, %d failed) | %s messages%s | %.1fs",
            len(results), ok, failed, f"{total:,}", extra, elapsed,
        )
    finally:
        storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Slack incremental sync tool")
    parser.add_argument("-c", "--config", help="Path to config YAML file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--since", help="Start date (YYYY-MM-DD). Overrides watermark and lookback_days.")
    parser.add_argument("--until", help="End date (YYYY-MM-DD). Only fetch messages before this date.")
    parser.add_argument("--download-files", action="store_true", help="Download file attachments.")
    parser.add_argument("--no-watermark", action="store_true", help="Ignore stored watermarks.")
    parser.add_argument("--dry-run", action="store_true", help="Estimate the run size without downloading anything.")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Never let the SDK/HTTP libraries dump request/response bodies (the collected
    # data) to the console, even in verbose mode. We only want our own progress.
    for noisy in ("slack_sdk", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
    except (ValueError, FileNotFoundError) as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    overrides: dict = {}
    if args.since:
        overrides["since"] = args.since
    if args.until:
        overrides["until"] = args.until
    if args.download_files:
        overrides["download_files"] = True
    if args.no_watermark:
        overrides["use_watermark"] = False
    if overrides:
        config = replace(config, **overrides)

    run(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
