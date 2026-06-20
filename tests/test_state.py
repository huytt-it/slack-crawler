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
        assert data["C001"] == "100.0"
