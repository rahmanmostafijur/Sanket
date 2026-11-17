"""Task counters in Redis, written by the real task runner inside RQ jobs (fakeredis)."""

from collections.abc import Mapping
from typing import Any

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from sanket.queue import runner
from sanket.queue.base import PermanentTaskError, TaskContext
from sanket.queue.stats import (
    UNKNOWN_TASK,
    Outcome,
    read_counters,
    record_outcome,
    stats_key,
    task_label,
)
from tests.queue_helpers import (
    CFG,
    make_queue,
    registry_of,
    run_burst,
    run_until_settled,
)

QUEUE = CFG.queue_name  # "test"


def counts(queue: Any) -> dict[tuple[str, str], int]:
    return {
        (outcome.value, task): value
        for (outcome, task), value in read_counters(queue.connection, QUEUE).items()
    }


def test_a_task_that_succeeds_is_counted_as_processed() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")
    queue.enqueue("work", {}, key="b")

    run_burst(queue, registry_of(work=lambda payload, context: None))

    assert counts(queue) == {("processed", "work"): 2}


def test_a_transient_failure_is_counted_as_retried_and_the_retry_as_processed() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")

    def flaky(payload: Mapping[str, Any], context: TaskContext) -> None:
        if context.attempt == 1:
            raise RuntimeError("provider timeout")

    run_until_settled(queue, registry_of(work=flaky))

    assert counts(queue) == {("retried", "work"): 1, ("processed", "work"): 1}


def test_a_task_that_uses_up_its_attempts_is_retried_then_failed() -> None:
    queue = make_queue()  # three attempts in all
    queue.enqueue("work", {}, key="a")

    def always(payload: Mapping[str, Any], context: TaskContext) -> None:
        raise RuntimeError("still broken")

    run_until_settled(queue, registry_of(work=always))

    assert counts(queue) == {("retried", "work"): 2, ("failed", "work"): 1}
    assert queue.health().dead_letters == 1


def test_a_permanent_failure_is_failed_at_once_without_a_retry() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")

    def bad(payload: Mapping[str, Any], context: TaskContext) -> None:
        raise PermanentTaskError("bad input")

    run_burst(queue, registry_of(work=bad))

    assert counts(queue) == {("failed", "work"): 1}


def test_counters_are_kept_per_task_name() -> None:
    queue = make_queue()
    queue.enqueue("embed", {}, key="a")
    queue.enqueue("match", {}, key="a")
    queue.enqueue("match", {}, key="b")

    run_burst(
        queue,
        registry_of(embed=lambda p, c: None, match=lambda p, c: None),
    )

    assert counts(queue) == {("processed", "embed"): 1, ("processed", "match"): 2}


def test_an_unregistered_task_name_is_counted_under_one_label() -> None:
    queue = make_queue()
    queue.enqueue("surprise-1", {}, key="a")
    queue.enqueue("surprise-2", {}, key="b")

    run_burst(queue, registry_of(work=lambda payload, context: None))

    assert counts(queue) == {("failed", UNKNOWN_TASK): 2}


def test_the_counters_live_in_one_hash_per_queue_and_survive_another_run() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")
    run_burst(queue, registry_of(work=lambda payload, context: None))
    queue.enqueue("work", {}, key="b")
    run_burst(queue, registry_of(work=lambda payload, context: None))

    assert queue.connection.hget(stats_key(QUEUE), "processed:work") == b"2"
    assert read_counters(queue.connection, "another-queue") == {}


def test_a_redis_failure_while_counting_does_not_fail_the_task(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")

    def broken(*args: object, **kwargs: object) -> None:
        raise RedisConnectionError("down")

    monkeypatch.setattr(runner, "record_outcome", broken)

    run_burst(queue, registry_of(work=lambda payload, context: None))

    health = queue.health()
    assert (health.depth, health.dead_letters) == (0, 0)
    assert "could not count a processed task: ConnectionError" in caplog.text


def test_a_call_outside_an_rq_job_counts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(runner, "record_outcome", lambda *args: calls.append(args))
    registry = registry_of(work=lambda payload, context: None)

    with runner.use_registry(registry):
        runner.execute_task("work", "{}")  # no current job, so no connection to count on

    assert calls == []


def test_record_and_read_round_trip_and_skip_garbled_fields() -> None:
    connection = fakeredis.FakeStrictRedis()
    record_outcome(connection, "q", "work", Outcome.PROCESSED)
    record_outcome(connection, "q", "work", Outcome.PROCESSED)
    record_outcome(connection, "q", "work", Outcome.FAILED)
    connection.hset(stats_key("q"), "bogus:work", "3")
    connection.hset(stats_key("q"), "processed:other", "not-a-number")

    assert read_counters(connection, "q") == {
        (Outcome.PROCESSED, "work"): 2,
        (Outcome.FAILED, "work"): 1,
    }


def test_task_labels_are_bounded_by_the_registered_names() -> None:
    assert task_label("embed_profile", ["embed_profile", "match_job"]) == "embed_profile"
    assert task_label("anything-else", ["embed_profile"]) == UNKNOWN_TASK
    assert task_label("embed_profile", []) == UNKNOWN_TASK
