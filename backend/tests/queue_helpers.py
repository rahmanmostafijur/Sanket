"""A queue on fakeredis and a worker that runs it in-process, for the queue and worker tests."""

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
from rq import SimpleWorker

from sanket.queue.base import Handler, TaskRegistry
from sanket.queue.config import QueueConfig
from sanket.queue.rq_queue import RqTaskQueue
from sanket.queue.runner import use_registry

# Small attempt budget and round backoff numbers, so schedules are easy to read in assertions.
CFG = QueueConfig(
    queue_name="test",
    max_attempts=3,
    backoff_base_seconds=10,
    backoff_factor=3,
    backoff_max_seconds=1000,
)
FAR_FUTURE = timedelta(days=365)


def make_queue(cfg: QueueConfig = CFG, clock: Callable[[], datetime] | None = None) -> RqTaskQueue:
    connection = fakeredis.FakeStrictRedis()
    if clock is None:
        return RqTaskQueue(connection, cfg)
    return RqTaskQueue(connection, cfg, clock)


def registry_of(**handlers: Handler) -> TaskRegistry:
    registry = TaskRegistry()
    for name, handler in handlers.items():
        registry.register(name, handler)
    return registry


def run_burst(queue: RqTaskQueue, registry: TaskRegistry) -> None:
    """Run every queued task once, in this process, then return."""
    logging.getLogger("rq.worker").setLevel(logging.ERROR)
    with use_registry(registry):
        worker = SimpleWorker([queue.queue], connection=queue.connection)
        worker.work(burst=True, logging_level="ERROR")


def run_until_settled(
    queue: RqTaskQueue, registry: TaskRegistry, max_rounds: int = 20, step: timedelta = FAR_FUTURE
) -> int:
    """Run, move the clock past every pending backoff, run again, until nothing is left."""
    now = datetime.now(UTC)
    for rounds in range(1, max_rounds + 1):
        run_burst(queue, registry)
        now += step
        if queue.promote_due(now) == 0 and queue.health().depth == 0:
            return rounds
    raise AssertionError("the queue did not settle")


@contextmanager
def recording_handler(
    action: Callable[[Mapping[str, Any], int], None] | None = None,
) -> Iterator[tuple[Handler, list[Mapping[str, Any]]]]:
    """A handler that records its payloads and calls `action(payload, call_number)`."""
    calls: list[Mapping[str, Any]] = []

    def handler(payload: Mapping[str, Any], context: Any) -> None:
        calls.append(payload)
        if action is not None:
            action(payload, len(calls))

    yield handler, calls
