"""Queue matching for the jobs an indexing run changed (ADR 0006).

After an applied indexing run, every job whose embedding was written gets a `match_job` task
(keyed by job and embedding hash, so the same embedding is never matched twice while pending)
and every job removed as dead gets one with `NO_EMBEDDING`, whose handler withdraws its
matches. Dry runs queue nothing: the indexing service only reports applied runs.

Nothing here may break indexing. A queue that is down is logged once and the run goes on; the
database stays the source of truth, and `python -m sanket.matching rematch --all-jobs` queues
whatever was missed. It stops at the first failure instead of waiting for a connection timeout
per job.
"""

import logging

from sanket.config import Settings
from sanket.indexing.service import IndexChanges, IndexObserver
from sanket.queue.base import EnqueueResult, TaskQueue
from sanket.queue.tasks import NO_EMBEDDING, TASK_MATCH_JOB, match_job_key

logger = logging.getLogger(__name__)


def _tasks(changes: IndexChanges) -> list[tuple[int, str]]:
    return [*changes.embedded, *((job_id, NO_EMBEDDING) for job_id in changes.removed)]


def enqueue_matches(queue: TaskQueue, changes: IndexChanges) -> int:
    """Queue the matching of the changed jobs; returns how many tasks were added. Never raises."""
    tasks = _tasks(changes)
    queued = 0
    for position, (job_id, embedding_hash) in enumerate(tasks):
        try:
            result = queue.enqueue(
                TASK_MATCH_JOB,
                {"job_id": job_id, "embedding_hash": embedding_hash},
                key=match_job_key(job_id, embedding_hash),
            )
        except Exception:  # the queue backend may fail in any way
            logger.exception(
                "Queueing matching tasks failed after %d of %d; indexing is unaffected, "
                "`python -m sanket.matching rematch --all-jobs --apply` queues what is missing",
                position,
                len(tasks),
            )
            return queued
        queued += result is EnqueueResult.ENQUEUED
    if tasks:
        logger.info("Queued %d matching tasks for %d changed jobs", queued, len(tasks))
    return queued


def index_observer(config: Settings, queue: TaskQueue | None) -> IndexObserver | None:
    """The observer for `index_pending` / `index_jobs`, or None when matching is not triggered
    (the setting is off or there is no queue)."""
    if not config.match_enqueue_after_indexing or queue is None:
        return None

    def observer(changes: IndexChanges) -> None:
        enqueue_matches(queue, changes)

    return observer


def index_observer_from_settings(config: Settings) -> IndexObserver | None:
    """`index_observer` with the Redis queue of REDIS_URL (none without it)."""
    if not config.match_enqueue_after_indexing:
        return None
    # Imported here so that importing this module never pulls in the Redis client.
    from sanket.queue.connection import task_queue_from_settings

    queue = task_queue_from_settings(config)
    if queue is None:
        logger.info("REDIS_URL is not set: matching is not queued after indexing")
    return index_observer(config, queue)
