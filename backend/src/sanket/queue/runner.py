"""The one function RQ runs: look a task's handler up and call it.

RQ job arguments are two strings, the task name and the JSON payload, so what sits in Redis is
readable and does not depend on our code layout. `execute_task` turns every problem with the
task itself (unknown name, payload that is not a JSON object, a handler raising
`PermanentTaskError`) into a permanent failure: the job goes to the dead-letter store at once
and the worker carries on. Any other exception is transient and retried with backoff.

Every run also adds to the task counters in Redis (`sanket.queue.stats`), which the API exports.
A failure to count is logged and never fails the task.
"""

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from rq import get_current_job

from sanket.observability.tracing import task_span
from sanket.queue.base import PermanentTaskError, TaskContext, TaskRegistry
from sanket.queue.stats import Outcome, record_outcome, task_label

logger = logging.getLogger(__name__)

TASK_FUNCTION = "sanket.queue.runner.execute_task"
META_TASK = "task"
META_KEY = "key"
META_MAX_ATTEMPTS = "max_attempts"
META_ATTEMPT = "attempt"
MAX_LOGGED_ERROR_CHARS = 300

_active_registry: TaskRegistry | None = None


def set_registry(registry: TaskRegistry | None) -> None:
    """Make `registry` the one `execute_task` uses (the worker calls this once at startup)."""
    global _active_registry
    _active_registry = registry


@contextmanager
def use_registry(registry: TaskRegistry) -> Iterator[None]:
    """Use `registry` for the duration of a block, for tests."""
    previous = _active_registry
    set_registry(registry)
    try:
        yield
    finally:
        set_registry(previous)


def _parse_payload(payload_json: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError) as error:
        raise PermanentTaskError(f"payload is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PermanentTaskError("payload must be a JSON object")
    return payload


def _context(task_name: str) -> TaskContext:
    """What this run is, from the RQ job it is part of (a lone call counts as attempt 1)."""
    job = get_current_job()
    if job is None:
        return TaskContext(task_name, None, 1, 1)
    max_attempts = int(job.meta.get(META_MAX_ATTEMPTS, 1))
    attempt = min(max_attempts, max(1, max_attempts - (job.retries_left or 0)))
    job.meta[META_ATTEMPT] = attempt
    job.save_meta()  # type: ignore[no-untyped-call]
    return TaskContext(task_name, job.meta.get(META_KEY), attempt, max_attempts)


def _give_up() -> None:
    """Tell RQ not to retry the current job: its next failure is the last."""
    job = get_current_job()
    if job is not None:
        job.retries_left = 0


def _short(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:MAX_LOGGED_ERROR_CHARS]


def _count(task_name: str, outcome: Outcome) -> None:
    """Add one to the counter of this run's outcome. Outside an RQ job there is nothing to
    count against, and a Redis failure must not turn a finished task into a failed one."""
    job = get_current_job()
    if job is None:
        return
    known = _active_registry.names() if _active_registry is not None else ()
    try:
        record_outcome(job.connection, job.origin, task_label(task_name, known), outcome)
    except Exception as error:  # noqa: BLE001 - counting is best effort
        logger.warning("could not count a %s task: %s", outcome.value, type(error).__name__)


def execute_task(task_name: str, payload_json: str) -> None:
    context = _context(task_name)
    try:
        if _active_registry is None:
            raise PermanentTaskError("no task registry is active in this process")
        handler = _active_registry.get(task_name)
        payload = _parse_payload(payload_json)
        with task_span(task_name, context.key, context.attempt):
            handler(payload, context)
    except PermanentTaskError as error:
        logger.error(
            "Task %s (key %s) failed permanently on attempt %d: %s",
            task_name,
            context.key,
            context.attempt,
            _short(error),
        )
        _give_up()
        _count(task_name, Outcome.FAILED)
        raise
    except Exception as error:
        final = context.is_final_attempt
        logger.error(
            "Task %s (key %s) failed on attempt %d of %d and %s: %s",
            task_name,
            context.key,
            context.attempt,
            context.max_attempts,
            "dead-lettered" if final else "will be retried",
            _short(error),
        )
        _count(task_name, Outcome.FAILED if final else Outcome.RETRIED)
        raise
    _count(task_name, Outcome.PROCESSED)
