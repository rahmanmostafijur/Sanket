"""Worker metrics for the API's `/metrics`, read from Redis at scrape time (ADR 0011).

The worker is a separate process without an HTTP server, so what it did is read from Redis: the
heartbeat keys (`sanket.worker.heartbeat`) say which workers are alive, and the task counters
(`sanket.queue.stats`) say how many tasks they ran. Series:

- `sanket_worker_up`: workers with a fresh heartbeat (0 when none).
- `sanket_worker_last_heartbeat_age_seconds{worker}`: age of each live worker's last beat.
- `sanket_worker_jobs_processed_total`, `_failed_total`, `_retried_total` `{queue,task}`.

When Redis cannot be read nothing is exported by this collector (`sanket_queue_up` is 0 then),
and the API carries on. The readings are cached for a few seconds, so an unreachable Redis costs
one timeout per interval, not one per scrape.
"""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from redis import Redis

from sanket.config import Settings
from sanket.queue.rq_queue import RqTaskQueue
from sanket.queue.stats import Outcome, read_counters
from sanket.worker.heartbeat import WorkerBeat, read_beats

logger = logging.getLogger(__name__)

CACHE_SECONDS = 10.0

Clock = Callable[[], float]

COUNTER_DOCS = {
    Outcome.PROCESSED: "Tasks whose handler returned.",
    Outcome.RETRIED: "Task runs that failed and were scheduled for a retry.",
    Outcome.FAILED: "Tasks that failed for good and were dead-lettered.",
}


@dataclass(frozen=True)
class _Reading:
    fetched_at: float
    beats: tuple[WorkerBeat, ...]
    counters: dict[tuple[Outcome, str], int]


class WorkerCollector(Collector):
    def __init__(
        self,
        connection: Redis,
        queue_name: str,
        max_age_seconds: float,
        clock: Clock = time.monotonic,
        wall_clock: Clock = time.time,
    ) -> None:
        self._connection = connection
        self._queue_name = queue_name
        self._max_age = max_age_seconds
        self._clock = clock
        self._wall_clock = wall_clock
        self._cached: _Reading | None = None
        self._failed_at: float | None = None

    def _read(self) -> _Reading | None:
        now = self._clock()
        if self._cached is not None and now - self._cached.fetched_at < CACHE_SECONDS:
            return self._cached
        if self._failed_at is not None and now - self._failed_at < CACHE_SECONDS:
            return None
        try:
            beats = read_beats(
                self._connection, max_age_seconds=self._max_age, clock=self._wall_clock
            )
            counters = read_counters(self._connection, self._queue_name)
        except Exception as error:  # noqa: BLE001 - any failure must not fail the scrape
            logger.warning("worker metrics unavailable: %s", type(error).__name__)
            self._cached, self._failed_at = None, now
            return None
        self._cached, self._failed_at = _Reading(now, tuple(beats), counters), None
        return self._cached

    def collect(self) -> Iterable[Metric]:
        reading = self._read()
        if reading is None:
            return
        up = GaugeMetricFamily("sanket_worker_up", "Workers with a fresh heartbeat.")
        up.add_metric([], len(reading.beats))
        yield up
        age = GaugeMetricFamily(
            "sanket_worker_last_heartbeat_age_seconds",
            "Seconds since each live worker's last heartbeat.",
            labels=["worker"],
        )
        now = self._wall_clock()
        for beat in reading.beats:
            age.add_metric([beat.name], max(0.0, now - beat.beat_at))
        yield age
        yield from self._counters(reading.counters)

    def _counters(self, counters: dict[tuple[Outcome, str], int]) -> Iterable[Metric]:
        for outcome in Outcome:
            family = CounterMetricFamily(
                f"sanket_worker_jobs_{outcome.value}",
                COUNTER_DOCS[outcome],
                labels=["queue", "task"],
            )
            for (kind, task), count in sorted(counters.items()):
                if kind is outcome:
                    family.add_metric([self._queue_name, task], count)
            yield family


def worker_collector_for(queue: object, config: Settings) -> WorkerCollector | None:
    """The collector for a Redis-backed queue; None for any other queue (or none), which has
    no worker to report on."""
    if not isinstance(queue, RqTaskQueue):
        return None
    return WorkerCollector(
        queue.connection, queue.cfg.queue_name, config.worker_heartbeat_ttl_seconds
    )
