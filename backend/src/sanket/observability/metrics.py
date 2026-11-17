"""Prometheus metrics for the API, in a registry of its own.

Labels are bounded: the route is the matched path template (`/profiles/{profile_id}`), never the
raw path, and unmatched paths share the label `unmatched`, so scanners cannot create series.
Queue numbers (waiting, scheduled, running, oldest age, dead letters) are read from the task
queue when Prometheus scrapes, cached for a few seconds, and reported as unavailable when
Redis cannot be reached. What the worker process does (liveness, task counters) is read from
Redis by `sanket.observability.worker_metrics`, which is registered next to it when the queue is
backed by Redis.
"""

import logging
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from sanket.queue.base import QueueHealth, TaskQueue

if TYPE_CHECKING:
    from sanket.api.middleware import RequestRecord

logger = logging.getLogger(__name__)

# Seconds: a search with an embedding call takes a few hundred milliseconds, a timeout five.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
QUEUE_CACHE_SECONDS = 10.0

Clock = Callable[[], float]


class QueueCollector(Collector):
    """Queue gauges computed at scrape time."""

    def __init__(self, queue: TaskQueue | None, clock: Clock = time.monotonic) -> None:
        self._queue = queue
        self._clock = clock
        self._cached: tuple[float, QueueHealth | None] | None = None

    def _health(self) -> QueueHealth | None:
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < QUEUE_CACHE_SECONDS:
            return self._cached[1]
        try:
            assert self._queue is not None
            health: QueueHealth | None = self._queue.health()
        except Exception as error:  # noqa: BLE001 - any failure must not fail the scrape
            logger.warning("queue metrics unavailable: %s", type(error).__name__)
            health = None
        self._cached = (now, health)
        return health

    def collect(self) -> Iterable[Metric]:
        if self._queue is None:
            return
        health = self._health()
        up = GaugeMetricFamily("sanket_queue_up", "1 when the task queue could be read.")
        up.add_metric([], 0 if health is None else 1)
        yield up
        if health is None:
            return
        values = {
            "sanket_queue_waiting": ("Tasks waiting to run now.", health.depth),
            "sanket_queue_scheduled": ("Tasks waiting for a later time.", health.scheduled),
            "sanket_queue_running": ("Tasks running now.", health.running),
            "sanket_queue_dead_letters": ("Dead-lettered tasks.", health.dead_letters),
            "sanket_queue_oldest_waiting_age_seconds": (
                "Age of the longest-waiting task, 0 when none waits.",
                health.oldest_age_seconds or 0.0,
            ),
        }
        for name, (description, value) in values.items():
            gauge = GaugeMetricFamily(name, description)
            gauge.add_metric([], value)
            yield gauge


class ApiMetrics:
    def __init__(
        self,
        queue: TaskQueue | None = None,
        clock: Clock = time.monotonic,
        worker_collector: Collector | None = None,
    ) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "sanket_http_requests_total",
            "HTTP requests by method, route template and status.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "sanket_http_request_duration_seconds",
            "HTTP request duration by method and route template.",
            ["method", "route"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.registry.register(QueueCollector(queue, clock))
        if worker_collector is not None:
            self.registry.register(worker_collector)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests.labels(method, route, str(status)).inc()
        self.duration.labels(method, route).observe(seconds)

    def observe_request(self, record: "RequestRecord") -> None:
        self.observe(record.method, record.route, record.status, record.duration_seconds)
