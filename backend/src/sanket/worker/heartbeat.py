"""The worker's liveness signal: a Redis key it refreshes while it runs (ADR 0011).

A running worker writes `sanket:worker:heartbeat:<name>` = unix time, with a TTL, every few
seconds from a thread of its own. The thread keeps beating while the main thread is inside a
long task and while it waits for work, and it stops with the process: when the worker is killed
the key expires, and on a clean exit the worker deletes it. Readers (the API's metrics and the
`python -m sanket.worker --check` health check) treat a worker as alive while its key exists
and is fresh.

The thread uses a Redis client of its own. A forking RQ worker forks a child per task, and a
connection pool that another thread may hold at that moment must not be inherited.

The beat proves that the process is alive and can reach Redis, not that a task is progressing:
a task stuck in the worker is bounded by the task timeout, and a worker that is alive but not
consuming shows as a growing queue (`sanket_queue_oldest_waiting_age_seconds`).
"""

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from redis import Redis
from redis.exceptions import RedisError

from sanket.config import Settings

logger = logging.getLogger(__name__)

HEARTBEAT_PREFIX = "sanket:worker:heartbeat:"
SCAN_COUNT = 100
JOIN_TIMEOUT_SECONDS = 5.0

Clock = Callable[[], float]


def heartbeat_key(name: str) -> str:
    return f"{HEARTBEAT_PREFIX}{name}"


def worker_name(config: Settings) -> str:
    """The name of this worker's key: WORKER_NAME, else the host name (the container id)."""
    return config.worker_name or socket.gethostname()


@dataclass(frozen=True)
class WorkerBeat:
    name: str
    beat_at: float
    age_seconds: float


def _parse_beat(raw: bytes | str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class Heartbeat:
    """Writes the heartbeat key now and then every `interval_seconds` until stopped."""

    def __init__(
        self,
        connection: Redis,
        name: str,
        *,
        interval_seconds: float,
        ttl_seconds: int,
        clock: Clock = time.time,
    ) -> None:
        self._connection = connection
        self._key = heartbeat_key(name)
        self._interval = interval_seconds
        self._ttl = ttl_seconds
        self._clock = clock
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> bool:
        """Write the key with a fresh time and TTL; False (logged) when Redis refuses."""
        try:
            self._connection.set(self._key, f"{self._clock():.3f}", ex=self._ttl)
        except RedisError as error:
            logger.warning("worker heartbeat not written: %s", type(error).__name__)
            return False
        return True

    def start(self) -> None:
        """Beat once, then keep beating from a daemon thread."""
        if self._thread is not None:
            raise RuntimeError("the heartbeat is already running")
        self._stopped.clear()
        self.beat()
        self._thread = threading.Thread(target=self._run, name="worker-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(self._interval):
            self.beat()

    def stop(self) -> None:
        """Stop beating and remove the key, so a clean shutdown is not mistaken for a crash."""
        self._stopped.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(JOIN_TIMEOUT_SECONDS)
        try:
            self._connection.delete(self._key)
        except RedisError as error:
            logger.warning("worker heartbeat not removed: %s", type(error).__name__)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def read_beats(
    connection: Redis, *, max_age_seconds: float, clock: Clock = time.time
) -> list[WorkerBeat]:
    """The workers that are alive: a heartbeat key exists and its time is at most
    `max_age_seconds` old. Raises `RedisError` when Redis cannot be read."""
    now = clock()
    beats: list[WorkerBeat] = []
    for raw_key in connection.scan_iter(match=f"{HEARTBEAT_PREFIX}*", count=SCAN_COUNT):
        key = _decode(raw_key)
        beat_at = _parse_beat(connection.get(key))
        if beat_at is None:
            continue
        age = max(0.0, now - beat_at)
        if age <= max_age_seconds:
            beats.append(WorkerBeat(key.removeprefix(HEARTBEAT_PREFIX), beat_at, age))
    return sorted(beats, key=lambda beat: beat.name)


def beat_age(
    connection: Redis, name: str, *, max_age_seconds: float, clock: Clock = time.time
) -> float | None:
    """Seconds since this worker's last beat, or None when it has none or the beat is older
    than `max_age_seconds`. Raises `RedisError` when Redis cannot be read."""
    beat_at = _parse_beat(connection.get(heartbeat_key(name)))
    if beat_at is None:
        return None
    age = max(0.0, clock() - beat_at)
    return age if age <= max_age_seconds else None


def heartbeat_from_settings(
    config: Settings, connection: Redis, *, clock: Clock = time.time
) -> Heartbeat:
    return Heartbeat(
        connection,
        worker_name(config),
        interval_seconds=config.worker_heartbeat_interval_seconds,
        ttl_seconds=config.worker_heartbeat_ttl_seconds,
        clock=clock,
    )
