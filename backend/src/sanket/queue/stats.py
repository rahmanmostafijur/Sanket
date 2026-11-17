"""Task counters kept in Redis, so the API can export what the worker process did (ADR 0011).

The worker is a separate process with no HTTP server, so its own in-process counters cannot be
scraped. Instead the task runner adds one to a field of a Redis hash for every outcome, and the
API reads the hash when Prometheus scrapes (the same pattern as the queue gauges).

One hash per queue, `sanket:worker:stats:<queue>`, with a field `<outcome>:<task>`. The outcomes
are `processed` (the handler returned), `retried` (it failed and a retry is scheduled) and
`failed` (it failed for good and was dead-lettered). The task label is the registered task name,
or `unknown` for any other name, so the number of fields stays bounded. Counts are cumulative:
they survive worker restarts and reset only when Redis is wiped (Prometheus treats that as a
counter reset).
"""

import logging
from collections.abc import Iterable
from enum import StrEnum

from redis import Redis

logger = logging.getLogger(__name__)

STATS_PREFIX = "sanket:worker:stats:"
UNKNOWN_TASK = "unknown"


class Outcome(StrEnum):
    PROCESSED = "processed"
    RETRIED = "retried"
    FAILED = "failed"


def stats_key(queue_name: str) -> str:
    return f"{STATS_PREFIX}{queue_name}"


def task_label(task_name: str, known_tasks: Iterable[str]) -> str:
    return task_name if task_name in set(known_tasks) else UNKNOWN_TASK


def record_outcome(connection: Redis, queue_name: str, task: str, outcome: Outcome) -> None:
    connection.hincrby(stats_key(queue_name), f"{outcome.value}:{task}", 1)


def read_counters(connection: Redis, queue_name: str) -> dict[tuple[Outcome, str], int]:
    """Every counter of the queue as `{(outcome, task): count}`; fields that do not parse are
    skipped. Raises `RedisError` when Redis cannot be read."""
    counters: dict[tuple[Outcome, str], int] = {}
    for raw_field, raw_value in connection.hgetall(stats_key(queue_name)).items():
        field = raw_field.decode() if isinstance(raw_field, bytes) else str(raw_field)
        name, _, task = field.partition(":")
        try:
            counters[(Outcome(name), task)] = int(raw_value)
        except ValueError:
            logger.warning("ignoring the unreadable worker counter %r", field)
    return counters
