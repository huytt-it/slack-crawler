"""Tests for watermark state persistence."""

from __future__ import annotations

import json
from slack_sync.state import WatermarkStore


class TestWatermarkStore:
    def test_get_nonexistent_returns_none(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        assert store.get("C001") is None

    def test_set_and_get(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.set("C001", "1700000000.000100")
        assert store.get("C001") == "1700000000.000100"

    def test_persists_to_disk(self, tmp_path):
        store1 = WatermarkStore(str(tmp_path))
        store1.set("C001", "1700000000.000100")
        store1.set("C002", "1700000001.000200")

        store2 = WatermarkStore(str(tmp_path))
        assert store2.get("C001") == "1700000000.000100"
        assert store2.get("C002") == "1700000001.000200"

    def test_overwrites_existing_watermark(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.set("C001", "1700000000.000100")
        store.set("C001", "1700000099.000999")
        assert store.get("C001") == "1700000099.000999"

    def test_atomic_write(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.set("C001", "100.0")

        wm_file = tmp_path / "watermarks.json"
        tmp_file = tmp_path / "watermarks.tmp"
        assert wm_file.exists()
        assert not tmp_file.exists()

        data = json.loads(wm_file.read_text())
        assert data["C001"]["watermark"] == "100.0"

    def test_migrates_old_flat_format(self, tmp_path):
        wm_file = tmp_path / "watermarks.json"
        wm_file.write_text(json.dumps({"C001": "123.456"}))
        store = WatermarkStore(str(tmp_path))
        assert store.get("C001") == "123.456"


class TestRunLifecycle:
    def test_fresh_plan_creates_progress(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        plan = store.plan_run("C1", "100.0", None, use_watermark=True)
        assert plan.oldest == "100.0"
        assert plan.resuming is False

    def test_resume_continues_from_low(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.plan_run("C1", "100.0", None, use_watermark=True)
        store.checkpoint("C1", low="150.0", high="200.0")

        store2 = WatermarkStore(str(tmp_path))
        plan = store2.plan_run("C1", "100.0", None, use_watermark=True)
        assert plan.resuming is True
        assert plan.latest == "150.0"
        assert plan.high_start == "200.0"

    def test_complete_advances_watermark_and_clears_progress(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.plan_run("C1", "100.0", None, use_watermark=True)
        store.checkpoint("C1", low="150.0", high="200.0")
        store.complete("C1", "200.0", use_watermark=True, wrote_any=True, now_ts="999.0")

        assert store.get("C1") == "200.0"
        store2 = WatermarkStore(str(tmp_path))
        plan = store2.plan_run("C1", "200.0", None, use_watermark=True)
        assert plan.resuming is False

    def test_complete_empty_first_run_anchors_now(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.plan_run("C1", "100.0", None, use_watermark=True)
        store.complete("C1", "0", use_watermark=True, wrote_any=False, now_ts="999.0")
        assert store.get("C1") == "999.0"

    def test_no_watermark_does_not_advance(self, tmp_path):
        store = WatermarkStore(str(tmp_path))
        store.plan_run("C1", "100.0", None, use_watermark=False)
        store.complete("C1", "200.0", use_watermark=False, wrote_any=True, now_ts="999.0")
        assert store.get("C1") is None
