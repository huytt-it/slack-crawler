"""Thread-safe token-bucket rate limiter shared across worker threads."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """A token bucket that all API callers acquire from before each request.

    With channel-level parallelism, many threads hit the Slack API at once.
    A shared limiter caps the aggregate request rate so we stay within
    Slack's tier limits regardless of worker count.
    """

    def __init__(self, rate_per_sec: float, burst: int) -> None:
        self._rate = max(0.01, rate_per_sec)
        self._capacity = max(1, burst)
        self._tokens = float(self._capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self._rate
            time.sleep(wait)
