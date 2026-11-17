"""Async Redis clients for the live feed, opened per stream."""

from redis.asyncio import Redis as AsyncRedis

from sanket.config import Settings
from sanket.feed.subscription import RedisFactory


def redis_factory_from_settings(config: Settings) -> RedisFactory | None:
    """A factory of clients for REDIS_URL with short timeouts, or None without REDIS_URL.

    Each stream opens its own client and closes it when it ends: a subscribed connection
    cannot be shared, and a client made here is not tied to an event loop until it is used.
    """
    if config.redis_url is None:
        return None
    url = config.redis_url.get_secret_value()
    timeout = config.redis_timeout_seconds

    def factory() -> AsyncRedis:
        return AsyncRedis.from_url(
            url,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
            socket_keepalive=True,
        )

    return factory
