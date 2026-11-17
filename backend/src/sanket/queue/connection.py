"""Redis connection and queue construction from the settings."""

from redis import Redis

from sanket.config import Settings
from sanket.queue.config import config_from_settings
from sanket.queue.rq_queue import RqTaskQueue


def redis_connection(config: Settings) -> Redis:
    """A client for REDIS_URL with short timeouts, so an unreachable Redis fails fast.

    The client returns bytes, which RQ requires.
    """
    if config.redis_url is None:
        raise ValueError("REDIS_URL is not set")
    return Redis.from_url(
        config.redis_url.get_secret_value(),
        socket_connect_timeout=config.redis_timeout_seconds,
        socket_timeout=config.redis_timeout_seconds,
    )


def task_queue_from_settings(config: Settings) -> RqTaskQueue | None:
    """The RQ-backed queue, or None when REDIS_URL is not configured."""
    if config.redis_url is None:
        return None
    return RqTaskQueue(redis_connection(config), config_from_settings(config))
