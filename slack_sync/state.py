"""Watermark (sync state) persistence with per-page checkpointing.

State layout per channel:

    {
      "general": {
        "watermark": "1781925744.785339",   # newest ts fully synced (incremental marker)
        "progress": {                         # present only while a descent is in flight
          "params": "<oldest>|<latest>",      # guards resume against changed run params
          "low":  "1779...",                  # oldest ts written so far (resume sets latest=low)
          "high": "1781..."                   # newest ts of this descent (becomes watermark on done)
        }
      }
    }

Pagination runs newest -> oldest, so the watermark can only advance once the
whole descent completes. Mid-descent we persist `progress` after every page; a
crash resumes from `progress.low` (re-fetching only the boundary page).

Thread-safe: channels sync in parallel and each may write state.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunPlan:
    oldest: str
    latest: Optional[str]
    high_start: str
    resuming: bool


def _ts_max(a: Optional[str], b: Optional[str]) -> str:
    vals = [v for v in (a, b) if v]
    if not vals:
        return "0"
    return max(vals, key=float)


class WatermarkStore:
    """File-backed, thread-safe per-channel watermark + checkpoint store."""

    def __init__(self, state_dir: str) -> None:
        self._path = Path(state_dir) / "watermarks.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Migrate the old flat format {channel_id: ts_string}.
        for cid, val in raw.items():
            if isinstance(val, str):
                self._data[cid] = {"watermark": val}
            else:
                self._data[cid] = val
        logger.info("Loaded watermarks for %d channels.", len(self._data))

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        tmp.replace(self._path)

    # --- backward-compatible simple accessors (used by ad-hoc callers/tests) ---

    def get(self, channel_id: str) -> Optional[str]:
        entry = self._data.get(channel_id)
        return entry.get("watermark") if entry else None

    def set(self, channel_id: str, ts: str) -> None:
        with self._lock:
            self._data.setdefault(channel_id, {})["watermark"] = ts
            self._save_locked()

    # --- streaming sync lifecycle ---

    def plan_run(
        self,
        channel_id: str,
        oldest_bound: str,
        latest_bound: Optional[str],
        use_watermark: bool,
    ) -> RunPlan:
        """Decide the [oldest, latest] window for this run, resuming if possible.

        `oldest_bound`/`latest_bound` are the caller-resolved timestamps (from
        --since/--until, the watermark, or lookback). If an in-flight descent
        with matching params exists, the run resumes from where it stopped.
        """
        params_key = f"{oldest_bound}|{latest_bound or ''}"
        with self._lock:
            entry = self._data.setdefault(channel_id, {})
            wm = entry.get("watermark")
            prog = entry.get("progress")

            if prog and prog.get("params") == params_key:
                logger.info("Channel %s: resuming descent from %s.", channel_id, prog.get("low"))
                return RunPlan(
                    oldest=oldest_bound,
                    latest=prog.get("low") or latest_bound,
                    high_start=prog.get("high") or (wm or "0"),
                    resuming=True,
                )

            entry["progress"] = {
                "params": params_key,
                "low": latest_bound or "",
                "high": wm or "0",
            }
            self._save_locked()
            return RunPlan(
                oldest=oldest_bound,
                latest=latest_bound,
                high_start=wm or "0",
                resuming=False,
            )

    def checkpoint(self, channel_id: str, low: str, high: str) -> None:
        """Persist progress after a page (and its threads) are durably written."""
        with self._lock:
            prog = self._data.setdefault(channel_id, {}).setdefault("progress", {})
            prog["low"] = low
            prog["high"] = _ts_max(prog.get("high"), high)
            self._save_locked()

    def complete(
        self,
        channel_id: str,
        high: str,
        use_watermark: bool,
        wrote_any: bool,
        now_ts: str,
    ) -> None:
        """Finalize a channel: advance the watermark and clear progress."""
        with self._lock:
            entry = self._data.setdefault(channel_id, {})
            if use_watermark:
                if wrote_any:
                    entry["watermark"] = _ts_max(entry.get("watermark"), high)
                elif not entry.get("watermark"):
                    # Empty first run: anchor at now so we don't rescan lookback forever.
                    entry["watermark"] = now_ts
            entry.pop("progress", None)
            self._save_locked()
