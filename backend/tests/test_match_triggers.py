"""Queueing matching after an indexing run."""

import logging
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr

from sanket.config import Settings
from sanket.indexing.service import IndexChanges
from sanket.matching.triggers import enqueue_matches, index_observer, index_observer_from_settings
from sanket.queue.base import EnqueueResult
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import NO_EMBEDDING, TASK_MATCH_JOB, match_job_key

DATABASE_URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"


def settings(**overrides: Any) -> Settings:
    return Settings(database_url=DATABASE_URL, gemini_api_key=None, **overrides)


def test_every_embedded_job_gets_a_match_task_keyed_by_its_embedding_hash() -> None:
    queue = InMemoryTaskQueue()

    queued = enqueue_matches(queue, IndexChanges(embedded=((4, "h4"), (9, "h9"))))

    assert queued == 2
    assert [(t.task_name, t.key, dict(t.payload)) for t in queue.enqueued] == [
        (TASK_MATCH_JOB, match_job_key(4, "h4"), {"job_id": 4, "embedding_hash": "h4"}),
        (TASK_MATCH_JOB, match_job_key(9, "h9"), {"job_id": 9, "embedding_hash": "h9"}),
    ]


def test_every_removed_job_gets_a_task_that_withdraws_its_matches() -> None:
    queue = InMemoryTaskQueue()

    enqueue_matches(queue, IndexChanges(removed=(3, 5)))

    assert [(t.key, dict(t.payload)) for t in queue.enqueued] == [
        (match_job_key(3, NO_EMBEDDING), {"job_id": 3, "embedding_hash": NO_EMBEDDING}),
        (match_job_key(5, NO_EMBEDDING), {"job_id": 5, "embedding_hash": NO_EMBEDDING}),
    ]


def test_a_task_already_pending_is_not_queued_twice() -> None:
    queue = InMemoryTaskQueue()
    enqueue_matches(queue, IndexChanges(embedded=((4, "h4"),)))

    assert enqueue_matches(queue, IndexChanges(embedded=((4, "h4"),))) == 0
    assert len(queue.pending()) == 1


def test_a_changed_embedding_is_a_new_task() -> None:
    queue = InMemoryTaskQueue()
    enqueue_matches(queue, IndexChanges(embedded=((4, "h4"),)))

    assert enqueue_matches(queue, IndexChanges(embedded=((4, "h4-new"),))) == 1


def test_nothing_changed_queues_nothing() -> None:
    queue = InMemoryTaskQueue()

    assert enqueue_matches(queue, IndexChanges()) == 0
    assert queue.enqueued == []


class DownQueue(InMemoryTaskQueue):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def enqueue(
        self,
        task_name: str,
        payload: Any,
        key: str | None = None,
        delay: timedelta | None = None,
    ) -> EnqueueResult:
        self.attempts += 1
        raise ConnectionError("redis down")


def test_a_queue_failure_is_logged_once_and_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = DownQueue()

    with caplog.at_level(logging.ERROR):
        queued = enqueue_matches(queue, IndexChanges(embedded=((1, "a"), (2, "b")), removed=(3,)))

    assert queued == 0
    assert queue.attempts == 1  # no point waiting for a timeout per job
    assert caplog.text.count("Queueing matching tasks failed") == 1
    assert "rematch" in caplog.text


def test_the_observer_queues_what_the_indexing_run_changed() -> None:
    queue = InMemoryTaskQueue()
    observer = index_observer(settings(), queue)

    assert observer is not None
    observer(IndexChanges(embedded=((1, "a"),)))

    assert len(queue.enqueued) == 1


def test_there_is_no_observer_when_the_setting_is_off() -> None:
    config = settings(match_enqueue_after_indexing=False)

    assert index_observer(config, InMemoryTaskQueue()) is None


def test_there_is_no_observer_without_a_queue() -> None:
    assert index_observer(settings(), None) is None


def test_without_redis_configured_there_is_no_observer() -> None:
    assert index_observer_from_settings(settings(redis_url=None)) is None


def test_with_redis_configured_the_observer_uses_the_rq_queue() -> None:
    config = settings(redis_url=SecretStr("redis://127.0.0.1:1/0"))

    observer = index_observer_from_settings(config)

    assert observer is not None  # building it does not connect


def test_the_setting_off_builds_no_queue_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(config: Settings) -> None:
        raise AssertionError("a queue must not be built")

    monkeypatch.setattr("sanket.queue.connection.task_queue_from_settings", explode)
    config = settings(
        redis_url=SecretStr("redis://127.0.0.1:1/0"), match_enqueue_after_indexing=False
    )

    assert index_observer_from_settings(config) is None
