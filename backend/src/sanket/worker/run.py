"""Run the queue worker: build the task registry, install it and hand over to RQ.

The worker process is the only place that knows the task handlers, so it installs the registry
(`sanket.queue.runner.set_registry`) before anything runs. Which RQ worker class does the
work depends on the platform: `SimpleWorker` runs each task in the worker process (Windows has
no `fork`, and it is what the tests use), the forking `Worker` runs each task in a short-lived
child process (the Linux runtime), which isolates a task that leaks memory or crashes.

The scheduler (`with_scheduler`) moves due retries and delayed tasks into the queue, so backoff
only elapses while a worker runs. SIGINT and SIGTERM are RQ's warm shutdown: the task in
progress finishes, then the worker stops. A task that is lost to a hard kill is retried
(delivery is at least once, the handlers are idempotent).
"""

import logging
import sys
from typing import Literal

from redis import Redis
from redis.exceptions import RedisError
from rq import SimpleWorker, Worker
from rq.worker import BaseWorker
from sqlalchemy import Engine

from sanket.config import Settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient
from sanket.matching.notify import MatchNotifier
from sanket.matching.tasks import registry_from_settings
from sanket.queue.base import TaskRegistry
from sanket.queue.config import config_from_settings
from sanket.queue.connection import redis_connection
from sanket.queue.rq_queue import RqTaskQueue
from sanket.queue.runner import set_registry

logger = logging.getLogger(__name__)

WINDOWS = "win32"
WORKER_LOG_LEVEL: Literal["INFO"] = "INFO"


def choose_worker_class(*, simple: bool, platform: str = sys.platform) -> type[BaseWorker]:
    """`SimpleWorker` when asked for or on Windows, else the forking `Worker`."""
    return SimpleWorker if simple or platform == WINDOWS else Worker


def _connect(config: Settings, connection: Redis | None) -> Redis:
    if connection is not None:
        return connection
    if config.redis_url is None:
        raise SystemExit(
            "REDIS_URL is not set: the worker needs Redis (docker compose up -d redis)"
        )
    client = redis_connection(config)
    try:
        client.ping()
    except RedisError as error:
        # The URL may carry a password: say what failed, not where.
        raise SystemExit(f"cannot reach Redis ({type(error).__name__}); is it running?") from error
    return client


def run_worker(
    config: Settings,
    *,
    burst: bool,
    simple: bool,
    connection: Redis | None = None,
    registry: TaskRegistry | None = None,
    embedder: EmbeddingClient | None = None,
    notifier: MatchNotifier | None = None,
    db_engine: Engine = engine,
) -> bool:
    """Work the queue until it is empty (`burst`) or until stopped; True if any task ran.

    Everything but `config` is injectable for tests.
    """
    redis = _connect(config, connection)
    queue = RqTaskQueue(redis, config_from_settings(config))
    set_registry(
        registry
        or registry_from_settings(
            config, queue=queue, embedder=embedder, notifier=notifier, db_engine=db_engine
        )
    )
    worker_class = choose_worker_class(simple=simple)
    mode = "simple" if worker_class is SimpleWorker else "fork"
    logger.info(
        "worker starting queue=%s mode=%s burst=%s", queue.cfg.queue_name, mode, str(burst).lower()
    )
    # A forked task must not inherit a connection of this process.
    db_engine.dispose()
    worker = worker_class([queue.queue], connection=redis)
    did_work = bool(worker.work(burst=burst, with_scheduler=True, logging_level=WORKER_LOG_LEVEL))
    logger.info(
        "worker stopped succeeded=%d failed=%d",
        worker.successful_job_count,
        worker.failed_job_count,
    )
    return did_work
