"""Slack API client wrapper with rate-limit handling and retry logic."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_sync.ratelimit import PerMethodRateLimiter

logger = logging.getLogger(__name__)


class SlackClient:
    """Thin wrapper around slack_sdk.WebClient with automatic retry on 429 and transient errors.

    Safe to share across threads: slack_sdk.WebClient is stateless per call, and
    the optional PerMethodRateLimiter throttles each method's own Slack bucket.
    """

    TRANSIENT_ERRORS = ("timeout", "fatal_error", "internal_error", "request_timeout")

    def __init__(
        self,
        token: str,
        max_retries: int = 5,
        rate_limiter: Optional[PerMethodRateLimiter] = None,
    ) -> None:
        self._client = WebClient(token=token)
        self._max_retries = max_retries
        self._rate_limiter = rate_limiter

    def api_call(self, method: str, **kwargs: Any) -> dict:
        """Execute a Slack API method with retry on 429 and transient errors."""
        for attempt in range(1, self._max_retries + 1):
            if self._rate_limiter is not None:
                self._rate_limiter.acquire(method)
            try:
                response = getattr(self._client, method)(**kwargs)
                return response.data
            except SlackApiError as e:
                status = e.response.status_code if e.response else None
                error = e.response.get("error", "") if e.response else str(e)

                if status == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 30))
                    # Jitter avoids a thundering herd when many workers back off together.
                    jitter = random.uniform(0, min(5, retry_after))
                    logger.warning(
                        "Rate limited on %s (attempt %d/%d). Retrying in %.1fs.",
                        method, attempt, self._max_retries, retry_after + jitter,
                    )
                    time.sleep(retry_after + jitter)
                    continue

                if error in self.TRANSIENT_ERRORS:
                    backoff = min(2 ** attempt, 60) + random.uniform(0, 1)
                    logger.warning(
                        "Transient error '%s' on %s (attempt %d/%d). Retrying in %.1fs.",
                        error, method, attempt, self._max_retries, backoff,
                    )
                    time.sleep(backoff)
                    continue

                logger.error("Slack API error on %s: %s", method, error)
                raise

        raise RuntimeError(f"Exhausted {self._max_retries} retries for {method}")
