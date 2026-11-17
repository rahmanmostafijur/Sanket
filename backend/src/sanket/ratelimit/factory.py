"""Build the limiter the settings ask for."""

from sanket.config import Settings
from sanket.queue.connection import redis_connection
from sanket.ratelimit.limiter import (
    FallbackRateLimiter,
    MemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)


def limiter_from_settings(config: Settings) -> RateLimiter | None:
    """None when limiting is off; Redis (with a memory fallback) when REDIS_URL is set; else
    memory."""
    if not config.rate_limit_enabled:
        return None
    if config.redis_url is None:
        return MemoryRateLimiter()
    return FallbackRateLimiter(RedisRateLimiter(redis_connection(config)), MemoryRateLimiter())
