"""Tests for main sync orchestration logic."""

from __future__ import annotations

from datetime import timezone
from main import _date_to_ts


class TestDateToTs:
    def test_converts_date_string(self):
        ts = _date_to_ts("2025-01-01")
        assert ts == str(1735689600.0)

    def test_converts_midyear(self):
        ts = _date_to_ts("2025-06-15")
        assert float(ts) > 0
