"""The queue interface the rest of the code depends on, and the errors handlers can raise.

Nothing here imports RQ or Redis: handlers, triggers and tests work against these types, and
`sanket.queue.rq_queue` (production) and `sanket.queue.memory` (tests, other phases) implement
them.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol


class TaskError(Exception):
    """Base class of the errors the queue layer itself raises."""


class PermanentTaskError(TaskError):
    """A task that cannot succeed however often it is retried (bad payload, input rejected).

    A handler raises it to send the task to the dead-letter store at once, without retries.
    Any other exception is treated as transient and retried with backoff.
    """


class UnknownTaskError(PermanentTaskError):
    """No handler is registered under the task's name."""


class EnqueueResult(StrEnum):
    ENQUEUED = "enqueued"
    # A task with the same name and key is already pending, scheduled for a retry, running or
    # dead-lettered, so nothing was added.
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class TaskContext:
    """What a handler may know about the run it is part of."""

    task_name: str
    key: str | None
    attempt: int
    max_attempts: int

    @property
    def is_final_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


Handler = Callable[[Mapping[str, Any], TaskContext], None]


class TaskRegistry:
    """Task name to handler. Handlers must be idempotent: delivery is at least once."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler) -> None:
        if name in self._handlers:
            raise ValueError(f"a handler for {name!r} is already registered")
        self._handlers[name] = handler

    def get(self, name: str) -> Handler:
        try:
            return self._handlers[name]
        except KeyError:
            raise UnknownTaskError(f"no handler registered for task {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._handlers)


@dataclass(frozen=True)
class QueueHealth:
    """Numbers for a readiness probe."""

    # Tasks waiting to run now.
    depth: int
    # Tasks waiting for a later time (retries with backoff, delayed tasks).
    scheduled: int
    running: int
    # Age of the longest-waiting task in `depth`, or None when nothing is waiting.
    oldest_age_seconds: float | None
    dead_letters: int


@dataclass(frozen=True)
class DeadLetter:
    """A task that used up its attempts or failed permanently."""

    id: str
    task_name: str
    key: str | None
    payload: str
    attempts: int
    error: str
    failed_at: datetime | None


class TaskQueue(Protocol):
    def enqueue(
        self,
        task_name: str,
        payload: Mapping[str, Any],
        key: str | None = None,
        delay: timedelta | None = None,
    ) -> EnqueueResult:
        """Queue a task. With a `key`, a second task of the same name and key is not queued
        while the first is pending (see `EnqueueResult.DUPLICATE`). `delay` postpones the run.
        """
        ...

    def health(self) -> QueueHealth: ...


class DeadLetterStore(Protocol):
    def list_dead_letters(self, limit: int = 100) -> list[DeadLetter]: ...

    def requeue_dead_letter(self, dead_letter_id: str) -> EnqueueResult:
        """Queue the task again with a full set of attempts and drop the dead letter.
        Raises KeyError when there is no such dead letter."""
        ...

    def purge_dead_letters(self, ids: Sequence[str] | None = None) -> int:
        """Delete the given dead letters (all when `ids` is None); returns how many."""
        ...
