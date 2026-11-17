"""Health check of a running worker: `python -m sanket.worker --check` (ADR 0011).

Exits 0 only when this worker's heartbeat key is in Redis and fresh. It is what the compose
health check runs, so a worker that is wedged, cut off from Redis or not started yet is
`unhealthy`. It is meant for a process in the same container or host as the worker: the name of
the key is WORKER_NAME, else the host name, the same as the worker uses.
"""

import logging
import time

from redis import Redis
from redis.exceptions import RedisError

from sanket.config import Settings
from sanket.queue.connection import redis_connection
from sanket.worker.heartbeat import Clock, beat_age, worker_name

logger = logging.getLogger(__name__)

HEALTHY = 0
UNHEALTHY = 1


def check_worker_alive(
    config: Settings, connection: Redis | None = None, clock: Clock = time.time
) -> tuple[int, str]:
    """Exit status and a one-line reason (never the Redis URL)."""
    name = worker_name(config)
    if connection is None and config.redis_url is None:
        return UNHEALTHY, "REDIS_URL is not set: there is no heartbeat to read"
    client = connection if connection is not None else redis_connection(config)
    try:
        age = beat_age(
            client, name, max_age_seconds=config.worker_heartbeat_ttl_seconds, clock=clock
        )
    except RedisError as error:
        return UNHEALTHY, f"cannot read the heartbeat of worker {name}: {type(error).__name__}"
    if age is None:
        return UNHEALTHY, f"worker {name} has no fresh heartbeat"
    return HEALTHY, f"worker {name} is alive, last heartbeat {age:.1f}s ago"
