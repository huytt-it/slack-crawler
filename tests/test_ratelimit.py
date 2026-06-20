"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import time
from slack_sync.ratelimit import RateLimiter, PerMethodRateLimiter


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


def test_per_method_buckets_are_independent():
    # burst=1, slow refill: a second call on the SAME method must wait,
    # but a call on a DIFFERENT method draws from a fresh bucket immediately.
    limiter = PerMethodRateLimiter(rate_per_sec=1.0, burst=1)
    limiter.acquire("conversations_history")  # drains history bucket

    start = time.monotonic()
    limiter.acquire("conversations_replies")  # different bucket -> no wait
    assert time.monotonic() - start < 0.1

    start = time.monotonic()
    limiter.acquire("conversations_history")  # same bucket -> must wait ~1s
    assert time.monotonic() - start >= 0.5
