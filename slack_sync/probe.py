"""Cheap pre-flight estimation: one page per channel to size up a run.

Slack exposes no total message count, so we sample the first (newest) page and
extrapolate from its time-density. Estimates are order-of-magnitude — good for
picking worker counts, warning about disk, and printing an ETA, not for exact
progress. File sizes come from the `size` field and are exact for sampled files.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

from slack_sync.channels import Channel
from slack_sync.client import SlackClient

logger = logging.getLogger(__name__)


@dataclass
class ChannelEstimate:
    channel: Channel
    sampled: int
    has_more: bool
    est_messages: int
    est_files: int
    est_file_bytes: int


def probe_channel(
    client: SlackClient,
    channel: Channel,
    oldest: str,
    latest: str | None,
    page_size: int = 200,
) -> ChannelEstimate:
    kwargs: dict = {"channel": channel.id, "limit": page_size, "oldest": oldest}
    if latest:
        kwargs["latest"] = latest

    data = client.api_call("conversations_history", **kwargs)
    batch = data.get("messages", [])
    has_more = data.get("has_more", False)
    sampled = len(batch)

    files_in_page = sum(len(m.get("files", [])) for m in batch)
    bytes_in_page = sum(
        f.get("size", 0) for m in batch for f in m.get("files", [])
    )

    if not has_more or sampled < 2:
        est_messages = sampled
    else:
        ts_newest = float(batch[0].get("ts", 0))
        ts_oldest = float(batch[-1].get("ts", 0))
        span = ts_newest - ts_oldest
        window = ts_newest - float(oldest)
        if span > 0 and window > 0:
            density = sampled / span
            est_messages = max(sampled, int(density * window))
        else:
            est_messages = sampled

    if sampled > 0:
        scale = est_messages / sampled
        est_files = int(files_in_page * scale)
        est_bytes = int(bytes_in_page * scale)
    else:
        est_files = est_bytes = 0

    return ChannelEstimate(
        channel=channel,
        sampled=sampled,
        has_more=has_more,
        est_messages=est_messages,
        est_files=est_files,
        est_file_bytes=est_bytes,
    )


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def print_report(
    estimates: list[ChannelEstimate],
    output_dir: str,
    page_size: int,
    api_rate_per_sec: float,
    with_files: bool,
) -> None:
    """Print a human-readable estimate summary (used by --dry-run)."""
    total_msgs = sum(e.est_messages for e in estimates)
    total_files = sum(e.est_files for e in estimates)
    total_bytes = sum(e.est_file_bytes for e in estimates)
    est_pages = sum(max(1, -(-e.est_messages // page_size)) for e in estimates)
    eta_sec = est_pages / max(0.01, api_rate_per_sec)

    try:
        free = shutil.disk_usage(output_dir if output_dir else ".").free
    except OSError:
        free = -1

    print("\n" + "=" * 60)
    print("  DRY RUN - estimate only, nothing was downloaded")
    print("=" * 60)
    for e in sorted(estimates, key=lambda x: x.est_messages, reverse=True):
        flag = "" if e.has_more else "  (complete in 1 page)"
        print(f"  {e.channel.name:<28} ~{e.est_messages:>9,} msgs{flag}")
    print("-" * 60)
    print(f"  Channels:            {len(estimates):,}")
    print(f"  Est. messages:       ~{total_msgs:,}")
    print(f"  Est. history pages:  ~{est_pages:,}")
    print(f"  Est. history time:   ~{eta_sec / 60:.1f} min (at {api_rate_per_sec}/s)")
    if with_files:
        print(f"  Est. files:          ~{total_files:,}")
        print(f"  Est. file size:      ~{_human_bytes(total_bytes)}")
        if free >= 0:
            ok = "OK" if free > total_bytes else "INSUFFICIENT"
            print(f"  Disk free:           {_human_bytes(free)}  [{ok}]")
    print("=" * 60 + "\n")
