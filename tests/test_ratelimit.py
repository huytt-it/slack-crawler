"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import time
from slack_sync.ratelimit import RateLimiter


def test_burst_is_immediate():
    limiter = RateLimiter(rate_per_sec=1.0, burst=5)
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    assert time.monotonic() - start < 0.1


def test_throttles_beyond_burst():
    limiter = RateLimiter(rate_per_sec=10.0, burst=1)
    limiter.acquire()  # consume the only token
    start = time.monotonic()
    limiter.acquire()  # must wait ~0.1s for a refill
    assert time.monotonic() - start >= 0.05
