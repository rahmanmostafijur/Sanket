"""The RQ implementation of the queue interface (ADR 0005).

Job id `<task>-<key>`, enqueued with `unique=True` and `result_ttl=0`: a second task with the
same name and key is refused (`DUPLICATE`) while the first is queued, waiting for a retry or
running, and a finished task leaves nothing behind. A failed task stays in RQ's failed
registry, which is the dead-letter store, for `dead_letter_ttl_seconds`.

Retries are RQ's: `Retry(max=max_attempts - 1, interval=backoff_schedule)`. The scheduler that
moves a due retry into the queue runs inside a worker (`with_scheduler`); `promote_due` does the
same step for a given time, which is how tests move the clock without sleeping.
"""

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from redis import Redis
from rq import Queue, Retry
from rq.exceptions import DuplicateJobError, NoSuchJobError
from rq.job import Job
from rq.registry import FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry

from sanket.queue.base import DeadLetter, EnqueueResult, QueueHealth
from sanket.queue.config import QueueConfig, backoff_schedule
from sanket.queue.runner import (
    META_ATTEMPT,
    META_KEY,
    META_MAX_ATTEMPTS,
    META_TASK,
    TASK_FUNCTION,
)

logger = logging.getLogger(__name__)

# Characters RQ accepts in a job id. Other keys are hashed.
SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
HASHED_KEY_CHARS = 32
MAX_ERROR_CHARS = 500


def _utcnow() -> datetime:
    return datetime.now(UTC)


def job_id_for(task_name: str, key: str | None) -> str:
    """A fresh random id without a key, else `<task>-<key>` (the key hashed if it is not safe)."""
    if key is None:
        return f"{task_name}-{uuid.uuid4().hex}"
    safe = (
        key if SAFE_KEY.match(key) else hashlib.sha256(key.encode()).hexdigest()[:HASHED_KEY_CHARS]
    )
    return f"{task_name}-{safe}"


def encode_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RqTaskQueue:
    def __init__(
        self,
        connection: Redis,
        cfg: QueueConfig,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.connection = connection
        self.cfg = cfg
        self._clock = clock
        self.queue = Queue(cfg.queue_name, connection=connection)

    # -- enqueue ---------------------------------------------------------------------------

    def _options(
        self, task_name: str, payload: Mapping[str, Any], key: str | None
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "args": (task_name, encode_payload(payload)),
            "job_id": job_id_for(task_name, key),
            "unique": key is not None,
            "result_ttl": 0,
            "failure_ttl": self.cfg.dead_letter_ttl_seconds,
            "job_timeout": self.cfg.task_timeout_seconds,
            "description": f"{task_name} {key}" if key else task_name,
            "meta": {
                META_TASK: task_name,
                META_KEY: key,
                META_MAX_ATTEMPTS: self.cfg.max_attempts,
            },
        }
        if self.cfg.max_attempts > 1:
            options["retry"] = Retry(
                max=self.cfg.max_attempts - 1, interval=backoff_schedule(self.cfg)
            )
        return options

    def enqueue(
        self,
        task_name: str,
        payload: Mapping[str, Any],
        key: str | None = None,
        delay: timedelta | None = None,
    ) -> EnqueueResult:
        options = self._options(task_name, payload, key)
        try:
            if delay is not None and delay > timedelta(0):
                self.queue.enqueue_in(delay, TASK_FUNCTION, **options)
            else:
                self.queue.enqueue(TASK_FUNCTION, **options)
        except DuplicateJobError:
            logger.debug("Task %s (key %s) is already queued", task_name, key)
            return EnqueueResult.DUPLICATE
        return EnqueueResult.ENQUEUED

    # -- health ----------------------------------------------------------------------------

    def health(self) -> QueueHealth:
        """Counts without side effects (RQ's counting helpers would also clean registries)."""
        scheduled = self._scheduled().get_job_count(cleanup=False)
        running = StartedJobRegistry(queue=self.queue).get_job_count(cleanup=False)
        dead = FailedJobRegistry(queue=self.queue).get_job_count(cleanup=False)
        return QueueHealth(
            depth=self.queue.count,
            scheduled=scheduled,
            running=running,
            oldest_age_seconds=self._oldest_age_seconds(),
            dead_letters=dead,
        )

    def _oldest_age_seconds(self) -> float | None:
        oldest = self.queue.get_job_ids(0, 1)
        if not oldest:
            return None
        job = self.queue.fetch_job(oldest[0])
        if job is None or job.enqueued_at is None:
            return None
        enqueued = job.enqueued_at
        if enqueued.tzinfo is None:
            enqueued = enqueued.replace(tzinfo=UTC)
        return max(0.0, (self._clock() - enqueued).total_seconds())

    def _scheduled(self) -> ScheduledJobRegistry:
        return ScheduledJobRegistry(queue=self.queue)  # type: ignore[no-untyped-call]

    # -- time, for retries and delayed tasks -------------------------------------------------

    def promote_due(self, now: datetime | None = None) -> int:
        """Move tasks whose scheduled time has come into the queue; returns how many.

        A worker with its scheduler does this continuously. Tests call it with a later time
        than the real one to make a backoff elapse.
        """
        moment = now or self._clock()
        registry = self._scheduled()
        due = registry.get_jobs_to_schedule(int(moment.timestamp()))
        moved = 0
        for job in Job.fetch_many(due, connection=self.connection):
            if job is None:
                continue
            with self.connection.pipeline() as pipeline:
                self.queue._enqueue_job(job, pipeline=pipeline)
                registry.remove(job.id, pipeline=pipeline)
                pipeline.execute()
            moved += 1
        return moved

    # -- dead letters ------------------------------------------------------------------------

    def _failed(self) -> FailedJobRegistry:
        return FailedJobRegistry(queue=self.queue)

    def list_dead_letters(self, limit: int = 100) -> list[DeadLetter]:
        ids = self._failed().get_job_ids(0, max(limit, 1) - 1, cleanup=False)
        jobs = Job.fetch_many(ids, connection=self.connection)
        return [_dead_letter(job) for job in jobs if job is not None]

    def requeue_dead_letter(self, dead_letter_id: str) -> EnqueueResult:
        try:
            job = Job.fetch(dead_letter_id, connection=self.connection)
        except NoSuchJobError:
            raise KeyError(dead_letter_id) from None
        letter = _dead_letter(job)
        if self._failed().remove(job) == 0:
            raise KeyError(dead_letter_id)
        job.delete()
        return self.enqueue(letter.task_name, json.loads(letter.payload), letter.key)

    def purge_dead_letters(self, ids: Sequence[str] | None = None) -> int:
        registry = self._failed()
        targets = list(ids) if ids is not None else registry.get_job_ids(cleanup=False)
        purged = 0
        for job_id in targets:
            if registry.remove(job_id) == 0:
                continue
            try:
                Job.fetch(job_id, connection=self.connection).delete()
            except NoSuchJobError:
                pass
            purged += 1
        return purged


def _dead_letter(job: Job) -> DeadLetter:
    task_name, payload = job.args[0], job.args[1]
    result = job.latest_result()
    error = (result.exc_string or "") if result is not None else ""
    last_line = next((line for line in reversed(error.splitlines()) if line.strip()), "")
    return DeadLetter(
        id=job.id,
        task_name=str(job.meta.get(META_TASK, task_name)),
        key=job.meta.get(META_KEY),
        payload=str(payload),
        attempts=int(job.meta.get(META_ATTEMPT, 1)),
        error=last_line[:MAX_ERROR_CHARS],
        failed_at=job.ended_at.replace(tzinfo=UTC) if job.ended_at else None,
    )
