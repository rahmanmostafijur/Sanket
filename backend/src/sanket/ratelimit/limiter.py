"""Sliding-window-counter rate limiting: in memory, in Redis, and Redis with a memory fallback.

Each caller and bucket has a count per fixed window. The estimate of the last `window` seconds
is `previous * (1 - elapsed fraction) + current`, which smooths the burst a plain fixed window
allows at its boundary while keeping two counters per caller. A refused request is not counted,
so a client that backs off recovers. The clock is injectable for tests.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
# Memory limiter: drop counters of callers not seen for two windows once this many exist.
PRUNE_THRESHOLD = 10_000
FALLBACK_LOG_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    # Whole seconds to wait before retrying; 0 when allowed.
    retry_after: int


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        """Count one request for `key` (a caller and bucket) against `limit` per window."""
        ...


def _estimate(previous: int, current: int, fraction: float) -> float:
    return previous * (1 - fraction) + current


def _retry_after(previous: int, current: int, fraction: float, limit: int, window: int) -> int:
    """Seconds until one more request would fit, at least 1."""
    rest_of_window = max(1, math.ceil((1 - fraction) * window))
    if previous <= 0 or current >= limit:
        return rest_of_window
    needed = 1 - (limit - current - 1) / previous
    return min(rest_of_window, max(1, math.ceil((needed - fraction) * window)))


def _decide(previous: int, current: int, fraction: float, limit: int, window: int) -> Decision:
    """`current` includes the request being decided."""
    estimate = _estimate(previous, current, fraction)
    if estimate <= limit:
        return Decision(True, limit, max(0, math.floor(limit - estimate)), 0)
    retry = _retry_after(previous, current - 1, fraction, limit, window)
    return Decision(False, limit, 0, retry)


class MemoryRateLimiter:
    """Per process. Enough for one worker process or tests; Redis shares state across many."""

    def __init__(self, clock: Clock = time.time) -> None:
        self._clock = clock
        self._counts: dict[str, tuple[int, int, int]] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        now = self._clock()
        index = int(now // window_seconds)
        fraction = (now % window_seconds) / window_seconds
        stored_index, previous, current = self._counts.get(key, (index, 0, 0))
        if stored_index == index - 1:
            previous, current = current, 0
        elif stored_index != index:
            previous, current = 0, 0
        decision = _decide(previous, current + 1, fraction, limit, window_seconds)
        counted = current + 1 if decision.allowed else current
        self._counts[key] = (index, previous, counted)
        self._prune(index)
        return decision

    def _prune(self, index: int) -> None:
        if len(self._counts) <= PRUNE_THRESHOLD:
            return
        self._counts = {k: v for k, v in self._counts.items() if v[0] >= index - 1}


class RedisRateLimiter:
    """Shared by every API process through Redis; raises `RedisError` when it is unreachable."""

    def __init__(self, redis: Redis, clock: Clock = time.time, prefix: str = "sanket:rl") -> None:
        self._redis = redis
        self._clock = clock
        self._prefix = prefix

    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        now = self._clock()
        index = int(now // window_seconds)
        fraction = (now % window_seconds) / window_seconds
        current_key = f"{self._prefix}:{key}:{index}"
        previous_key = f"{self._prefix}:{key}:{index - 1}"
        pipe = self._redis.pipeline(transaction=False)
        pipe.incr(current_key)
        pipe.expire(current_key, 2 * window_seconds + 1)
        pipe.get(previous_key)
        current, _, raw_previous = pipe.execute()
        previous = int(raw_previous) if raw_previous else 0
        decision = _decide(previous, int(current), fraction, limit, window_seconds)
        if not decision.allowed:
            self._redis.decr(current_key)
        return decision


class FallbackRateLimiter:
    """Redis first; when it fails, count in memory instead, so a Redis outage never blocks the
    API and never leaves it unlimited either."""

    def __init__(
        self, primary: RateLimiter, fallback: RateLimiter, clock: Clock = time.time
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._clock = clock
        self._last_logged = -FALLBACK_LOG_INTERVAL_SECONDS

    def hit(self, key: str, limit: int, window_seconds: int) -> Decision:
        try:
            return self._primary.hit(key, limit, window_seconds)
        except RedisError as error:
            self._log_once(error)
            return self._fallback.hit(key, limit, window_seconds)

    def _log_once(self, error: Exception) -> None:
        now = self._clock()
        if now - self._last_logged >= FALLBACK_LOG_INTERVAL_SECONDS:
            self._last_logged = now
            logger.warning(
                "rate limiter: Redis failed (%s), counting in memory", type(error).__name__
            )
