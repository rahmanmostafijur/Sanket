"""The rate limiters: sliding window counting, Redis sharing and the memory fallback."""

from collections.abc import Callable
from typing import Any

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from sanket.ratelimit.limiter import (
    FallbackRateLimiter,
    MemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)

WINDOW = 60


class Clock:
    def __init__(self, now: float = 6000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def memory(clock: Clock) -> RateLimiter:
    return MemoryRateLimiter(clock)


def redis_backed(clock: Clock) -> RateLimiter:
    return RedisRateLimiter(fakeredis.FakeRedis(), clock)


Factory = Callable[[Clock], RateLimiter]
BOTH = pytest.mark.parametrize("make", [memory, redis_backed], ids=["memory", "redis"])


@BOTH
def test_requests_up_to_the_limit_pass_and_the_next_is_refused(make: Factory) -> None:
    limiter = make(Clock())

    decisions = [limiter.hit("k", 3, WINDOW) for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert decisions[3].retry_after >= 1


@BOTH
def test_callers_and_buckets_are_counted_separately(make: Factory) -> None:
    limiter = make(Clock())
    limiter.hit("default:owner:a", 1, WINDOW)

    assert not limiter.hit("default:owner:a", 1, WINDOW).allowed
    assert limiter.hit("default:owner:b", 1, WINDOW).allowed
    assert limiter.hit("search:owner:a", 1, WINDOW).allowed


@BOTH
def test_the_budget_returns_after_the_window_passes(make: Factory) -> None:
    clock = Clock()
    limiter = make(clock)
    for _ in range(3):
        limiter.hit("k", 3, WINDOW)
    assert not limiter.hit("k", 3, WINDOW).allowed

    clock.now += 2 * WINDOW

    assert limiter.hit("k", 3, WINDOW).allowed


@BOTH
def test_the_previous_window_still_counts_part_way_into_the_next(make: Factory) -> None:
    clock = Clock(6000.0 + 59)  # the end of a window
    limiter = make(clock)
    for _ in range(4):
        limiter.hit("k", 4, WINDOW)

    clock.now += 3  # just into the next window: the old four still weigh almost fully
    early = limiter.hit("k", 4, WINDOW)
    clock.now += 45  # most of the way through: their weight has mostly gone
    late = limiter.hit("k", 4, WINDOW)

    assert not early.allowed
    assert late.allowed


@BOTH
def test_a_refused_request_is_not_counted(make: Factory) -> None:
    clock = Clock()
    limiter = make(clock)
    for _ in range(2):
        limiter.hit("k", 2, WINDOW)
    for _ in range(50):
        assert not limiter.hit("k", 2, WINDOW).allowed

    clock.now += WINDOW * 1.5  # half way into the next window: the first two weigh one

    assert limiter.hit("k", 2, WINDOW).allowed


@BOTH
def test_retry_after_is_within_the_window_and_waiting_it_out_works(make: Factory) -> None:
    clock = Clock()
    limiter = make(clock)
    for _ in range(3):
        limiter.hit("k", 3, WINDOW)
    refused = limiter.hit("k", 3, WINDOW)

    assert 1 <= refused.retry_after <= WINDOW
    clock.now += refused.retry_after + WINDOW  # well past it
    assert limiter.hit("k", 3, WINDOW).allowed


def test_two_limiters_on_one_redis_share_their_counts() -> None:
    clock = Clock()
    shared = fakeredis.FakeRedis()
    first, second = RedisRateLimiter(shared, clock), RedisRateLimiter(shared, clock)

    first.hit("k", 2, WINDOW)
    second.hit("k", 2, WINDOW)

    assert not first.hit("k", 2, WINDOW).allowed


def test_redis_keys_expire() -> None:
    clock = Clock()
    server = fakeredis.FakeRedis()
    RedisRateLimiter(server, clock).hit("k", 2, WINDOW)

    [key] = server.keys("sanket:rl:*")

    assert 0 < server.ttl(key) <= 2 * WINDOW + 1


class BrokenRedis(RedisRateLimiter):
    def __init__(self) -> None:
        pass

    def hit(self, key: str, limit: int, window_seconds: int) -> Any:
        raise RedisConnectionError("down")


def test_when_redis_fails_the_memory_fallback_still_limits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    limiter = FallbackRateLimiter(BrokenRedis(), MemoryRateLimiter(clock), clock)

    decisions = [limiter.hit("k", 2, WINDOW).allowed for _ in range(3)]

    assert decisions == [True, True, False]
    assert len([r for r in caplog.records if "Redis failed" in r.message]) == 1


def test_the_fallback_uses_redis_when_it_works() -> None:
    clock = Clock()
    shared = fakeredis.FakeRedis()
    limiter = FallbackRateLimiter(RedisRateLimiter(shared, clock), MemoryRateLimiter(clock), clock)

    limiter.hit("k", 2, WINDOW)

    assert shared.keys("sanket:rl:*")


def test_the_memory_limiter_forgets_idle_callers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sanket.ratelimit.limiter.PRUNE_THRESHOLD", 5)
    clock = Clock()
    limiter = MemoryRateLimiter(clock)
    for number in range(10):
        limiter.hit(f"old-{number}", 5, WINDOW)

    clock.now += 5 * WINDOW
    limiter.hit("new", 5, WINDOW)

    assert list(limiter._counts) == ["new"]
