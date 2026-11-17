"""An in-memory queue for tests and for code that must run without Redis.

It records what is enqueued and applies the same idempotent-key rule as the real queue, but it
runs nothing by itself: `take_all()` hands the pending tasks to the caller, and
`run_pending(registry)` runs them once, which is enough to test a trigger or a handler chain.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sanket.queue.base import EnqueueResult, QueueHealth, TaskContext, TaskRegistry


@dataclass(frozen=True)
class QueuedTask:
    task_name: str
    payload: Mapping[str, Any]
    key: str | None
    delay: timedelta | None


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._pending: list[QueuedTask] = []
        self.enqueued: list[QueuedTask] = []

    def enqueue(
        self,
        task_name: str,
        payload: Mapping[str, Any],
        key: str | None = None,
        delay: timedelta | None = None,
    ) -> EnqueueResult:
        json.dumps(payload)  # a payload the real queue could not carry fails here too
        if key is not None and any(
            t.task_name == task_name and t.key == key for t in self._pending
        ):
            return EnqueueResult.DUPLICATE
        task = QueuedTask(task_name, dict(payload), key, delay)
        self._pending.append(task)
        self.enqueued.append(task)
        return EnqueueResult.ENQUEUED

    def pending(self, task_name: str | None = None) -> list[QueuedTask]:
        return [t for t in self._pending if task_name in (None, t.task_name)]

    def take_all(self) -> list[QueuedTask]:
        tasks, self._pending = self._pending, []
        return tasks

    def run_pending(self, registry: TaskRegistry, max_attempts: int = 1) -> int:
        """Run each pending task once, in order, including tasks they enqueue; returns the
        number run. A handler error propagates."""
        ran = 0
        while self._pending:
            task = self._pending.pop(0)
            registry.get(task.task_name)(
                task.payload, TaskContext(task.task_name, task.key, 1, max_attempts)
            )
            ran += 1
        return ran

    def health(self) -> QueueHealth:
        return QueueHealth(
            depth=len(self._pending),
            scheduled=0,
            running=0,
            oldest_age_seconds=None,
            dead_letters=0,
        )
