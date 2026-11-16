"""The RQ-backed queue on fakeredis: idempotent keys, retries with backoff, dead letters."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from rq.registry import ScheduledJobRegistry

from sanket.queue.base import (
    EnqueueResult,
    PermanentTaskError,
    TaskContext,
    TaskRegistry,
    UnknownTaskError,
)
from sanket.queue.config import QueueConfig, backoff_schedule
from sanket.queue.rq_queue import job_id_for
from sanket.queue.runner import TASK_FUNCTION
from tests.queue_helpers import (
    CFG,
    FAR_FUTURE,
    make_queue,
    recording_handler,
    registry_of,
    run_burst,
    run_until_settled,
)

# --- backoff schedule ---------------------------------------------------------------------


def test_backoff_grows_by_the_factor_and_is_capped() -> None:
    cfg = QueueConfig(
        max_attempts=6, backoff_base_seconds=10, backoff_factor=3, backoff_max_seconds=100
    )

    assert backoff_schedule(cfg) == [10, 30, 90, 100, 100]


def test_one_attempt_means_no_retries() -> None:
    assert backoff_schedule(QueueConfig(max_attempts=1)) == []


def test_backoff_rounds_up_to_whole_seconds() -> None:
    cfg = QueueConfig(max_attempts=3, backoff_base_seconds=0.2, backoff_factor=1.5)

    assert backoff_schedule(cfg) == [1, 1]


# --- enqueue and run ----------------------------------------------------------------------


def test_an_enqueued_task_runs_its_handler_with_the_payload_and_context() -> None:
    queue = make_queue()
    seen: list[tuple[Mapping[str, Any], TaskContext]] = []
    registry = registry_of(work=lambda payload, context: seen.append((payload, context)))

    assert queue.enqueue("work", {"n": 1, "text": "café"}, key="k1") is EnqueueResult.ENQUEUED
    run_burst(queue, registry)

    assert [payload for payload, _ in seen] == [{"n": 1, "text": "café"}]
    context = seen[0][1]
    assert (context.task_name, context.key, context.attempt, context.max_attempts) == (
        "work",
        "k1",
        1,
        CFG.max_attempts,
    )
    assert queue.health().dead_letters == 0
    assert queue.health().depth == 0


def test_the_same_key_while_pending_is_one_task() -> None:
    queue = make_queue()
    with recording_handler() as (handler, calls):
        registry = registry_of(work=handler)

        first = queue.enqueue("work", {"n": 1}, key="job-7")
        second = queue.enqueue("work", {"n": 1}, key="job-7")
        run_burst(queue, registry)

    assert (first, second) == (EnqueueResult.ENQUEUED, EnqueueResult.DUPLICATE)
    assert len(calls) == 1


def test_a_key_can_be_used_again_once_its_task_has_finished() -> None:
    queue = make_queue()
    with recording_handler() as (handler, calls):
        registry = registry_of(work=handler)
        queue.enqueue("work", {"n": 1}, key="again")
        run_burst(queue, registry)

        result = queue.enqueue("work", {"n": 2}, key="again")
        run_burst(queue, registry)

    assert result is EnqueueResult.ENQUEUED
    assert [call["n"] for call in calls] == [1, 2]


def test_tasks_with_different_names_may_share_a_key() -> None:
    queue = make_queue()

    assert queue.enqueue("a", {}, key="k") is EnqueueResult.ENQUEUED
    assert queue.enqueue("b", {}, key="k") is EnqueueResult.ENQUEUED


def test_without_a_key_nothing_is_deduplicated() -> None:
    queue = make_queue()

    assert queue.enqueue("work", {"n": 1}) is EnqueueResult.ENQUEUED
    assert queue.enqueue("work", {"n": 1}) is EnqueueResult.ENQUEUED
    assert queue.health().depth == 2


def test_a_key_with_unusual_characters_is_hashed_into_a_valid_id() -> None:
    queue = make_queue()
    key = "profile:5/hash with spaces"

    assert queue.enqueue("work", {}, key=key) is EnqueueResult.ENQUEUED
    assert queue.enqueue("work", {}, key=key) is EnqueueResult.DUPLICATE
    assert job_id_for("work", key) == job_id_for("work", key)
    assert job_id_for("work", key) != job_id_for("work", "profile:6/hash with spaces")


def test_a_delayed_task_waits_until_its_time() -> None:
    queue = make_queue()
    with recording_handler() as (handler, calls):
        registry = registry_of(work=handler)
        queue.enqueue("work", {"n": 1}, key="later", delay=timedelta(minutes=5))

        run_burst(queue, registry)
        assert calls == []
        assert queue.health().scheduled == 1

        assert queue.promote_due(datetime.now(UTC) + timedelta(minutes=6)) == 1
        run_burst(queue, registry)

    assert len(calls) == 1


def test_a_delayed_task_is_still_unique_by_key() -> None:
    queue = make_queue()

    first = queue.enqueue("work", {}, key="k", delay=timedelta(minutes=5))
    second = queue.enqueue("work", {}, key="k")

    assert (first, second) == (EnqueueResult.ENQUEUED, EnqueueResult.DUPLICATE)


# --- retries with backoff -----------------------------------------------------------------


def failing(error: Exception, until_call: int | None = None) -> Any:
    def action(payload: Mapping[str, Any], call: int) -> None:
        if until_call is None or call <= until_call:
            raise error

    return action


def test_a_transient_failure_is_retried_after_the_backoff_not_before() -> None:
    queue = make_queue()
    with recording_handler(failing(RuntimeError("provider down"))) as (handler, calls):
        registry = registry_of(work=handler)
        queue.enqueue("work", {}, key="t1")
        before = datetime.now(UTC)

        run_burst(queue, registry)

        assert len(calls) == 1
        scheduled = ScheduledJobRegistry(queue=queue.queue)
        due = scheduled.get_scheduled_time(job_id_for("work", "t1"))
        first_delay = backoff_schedule(CFG)[0]
        assert before + timedelta(seconds=first_delay - 1) <= due
        assert due <= datetime.now(UTC) + timedelta(seconds=first_delay + 1)
        # Nothing is due yet, so another run does nothing.
        run_burst(queue, registry)
        assert len(calls) == 1


def test_each_retry_waits_longer_and_the_task_is_dead_lettered_after_the_last_attempt() -> None:
    queue = make_queue()
    delays: list[float] = []
    with recording_handler(failing(RuntimeError("provider down"))) as (handler, calls):
        registry = registry_of(work=handler)
        queue.enqueue("work", {"n": 9}, key="t2")
        scheduled = ScheduledJobRegistry(queue=queue.queue)
        job_id = job_id_for("work", "t2")
        for _ in range(CFG.max_attempts):
            run_burst(queue, registry)
            if queue.health().scheduled:
                due = scheduled.get_scheduled_time(job_id)
                delays.append((due - datetime.now(UTC)).total_seconds())
                queue.promote_due(datetime.now(UTC) + FAR_FUTURE)

    assert len(calls) == CFG.max_attempts
    assert delays[0] == pytest.approx(10, abs=2)
    assert delays[1] == pytest.approx(30, abs=2)
    health = queue.health()
    assert (health.dead_letters, health.depth, health.scheduled) == (1, 0, 0)
    [letter] = queue.list_dead_letters()
    assert (letter.task_name, letter.key, letter.attempts) == ("work", "t2", CFG.max_attempts)
    assert "provider down" in letter.error
    assert json.loads(letter.payload) == {"n": 9}


def test_a_task_that_recovers_leaves_no_dead_letter() -> None:
    queue = make_queue()
    attempts: list[int] = []

    def handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        attempts.append(context.attempt)
        if context.attempt < 3:
            raise ConnectionError("temporary")

    queue.enqueue("work", {}, key="r1")
    run_until_settled(queue, registry_of(work=handler))

    assert attempts == [1, 2, 3]
    assert queue.health().dead_letters == 0


def test_the_last_attempt_is_marked_so_handlers_can_record_a_final_failure() -> None:
    queue = make_queue()
    finals: list[bool] = []

    def handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        finals.append(context.is_final_attempt)
        raise RuntimeError("always")

    queue.enqueue("work", {}, key="f1")
    run_until_settled(queue, registry_of(work=handler))

    assert finals == [False, False, True]


def test_a_dead_lettered_key_is_not_enqueued_again_until_it_is_requeued_or_purged() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="stuck")
    run_until_settled(queue, registry_of(work=failing_always))

    assert queue.enqueue("work", {}, key="stuck") is EnqueueResult.DUPLICATE


def failing_always(payload: Mapping[str, Any], context: TaskContext) -> None:
    raise RuntimeError("nope")


# --- poison tasks -------------------------------------------------------------------------


def test_a_permanent_error_is_dead_lettered_without_retries() -> None:
    queue = make_queue()

    def handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        raise PermanentTaskError("bad input")

    queue.enqueue("work", {}, key="p1")
    run_burst(queue, registry_of(work=handler))

    assert queue.health().scheduled == 0
    [letter] = queue.list_dead_letters()
    assert letter.attempts == 1
    assert "bad input" in letter.error


def test_an_unknown_task_is_dead_lettered_and_the_worker_goes_on() -> None:
    queue = make_queue()
    with recording_handler() as (handler, calls):
        queue.enqueue("mystery", {}, key="x")
        queue.enqueue("work", {"n": 1}, key="y")

        run_burst(queue, registry_of(work=handler))

    assert len(calls) == 1
    [letter] = queue.list_dead_letters()
    assert letter.task_name == "mystery"
    assert UnknownTaskError.__name__ in letter.error


@pytest.mark.parametrize("payload", ["{not json", "[1, 2]", "", "null"])
def test_a_payload_that_is_not_a_json_object_is_dead_lettered(payload: str) -> None:
    queue = make_queue()
    with recording_handler() as (handler, calls):
        queue.queue.enqueue(
            TASK_FUNCTION, args=("work", payload), job_id="work-poison", meta={"task": "work"}
        )
        queue.enqueue("work", {"n": 1}, key="after")

        run_burst(queue, registry_of(work=handler))

    assert calls == [{"n": 1}]
    assert [letter.id for letter in queue.list_dead_letters()] == ["work-poison"]


def test_running_without_a_registry_is_a_permanent_failure_not_a_crash() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="orphan")

    run_burst(queue, TaskRegistry())

    assert queue.health().dead_letters == 1


# --- dead letters: list, requeue, purge ----------------------------------------------------


def dead_letter_two_tasks(queue: Any) -> list[str]:
    queue.enqueue("work", {"n": 1}, key="d1")
    queue.enqueue("work", {"n": 2}, key="d2")
    run_until_settled(queue, registry_of(work=failing_always))
    return [letter.id for letter in queue.list_dead_letters()]


def test_dead_letters_can_be_listed_with_a_limit() -> None:
    queue = make_queue()
    ids = dead_letter_two_tasks(queue)

    assert sorted(ids) == [job_id_for("work", "d1"), job_id_for("work", "d2")]
    assert len(queue.list_dead_letters(limit=1)) == 1


def test_a_requeued_dead_letter_runs_again_with_a_full_set_of_attempts() -> None:
    queue = make_queue()
    dead_letter_two_tasks(queue)
    attempts: list[int] = []

    def fixed(payload: Mapping[str, Any], context: TaskContext) -> None:
        attempts.append(context.attempt)

    result = queue.requeue_dead_letter(job_id_for("work", "d1"))
    run_burst(queue, registry_of(work=fixed))

    assert result is EnqueueResult.ENQUEUED
    assert attempts == [1]
    assert [letter.key for letter in queue.list_dead_letters()] == ["d2"]


def test_a_requeued_task_that_fails_again_gets_all_its_attempts_before_dead_lettering() -> None:
    queue = make_queue()
    dead_letter_two_tasks(queue)
    calls: list[int] = []

    def still_broken(payload: Mapping[str, Any], context: TaskContext) -> None:
        calls.append(context.attempt)
        raise RuntimeError("still")

    queue.requeue_dead_letter(job_id_for("work", "d1"))
    run_until_settled(queue, registry_of(work=still_broken))

    assert calls == [1, 2, 3]


def test_requeueing_an_unknown_dead_letter_raises() -> None:
    queue = make_queue()

    with pytest.raises(KeyError):
        queue.requeue_dead_letter("work-nothing")


def test_requeueing_something_that_is_not_dead_lettered_raises_and_keeps_it() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="live")

    with pytest.raises(KeyError):
        queue.requeue_dead_letter(job_id_for("work", "live"))

    assert queue.health().depth == 1


def test_purge_removes_the_named_dead_letters_or_all_of_them() -> None:
    queue = make_queue()
    dead_letter_two_tasks(queue)

    assert queue.purge_dead_letters([job_id_for("work", "d1"), "work-missing"]) == 1
    assert [letter.key for letter in queue.list_dead_letters()] == ["d2"]
    assert queue.purge_dead_letters() == 1
    assert queue.list_dead_letters() == []
    # A purged key can be queued again.
    assert queue.enqueue("work", {}, key="d1") is EnqueueResult.ENQUEUED


# --- health -------------------------------------------------------------------------------


def test_health_reports_depth_the_age_of_the_oldest_task_and_dead_letters() -> None:
    current = [datetime.now(UTC)]
    queue = make_queue(clock=lambda: current[0])

    assert queue.health().oldest_age_seconds is None

    queue.enqueue("work", {}, key="a")
    queue.enqueue("work", {}, key="b")
    current[0] += timedelta(seconds=90)
    health = queue.health()

    assert health.depth == 2
    assert health.oldest_age_seconds == pytest.approx(90, abs=3)
    assert (health.scheduled, health.running, health.dead_letters) == (0, 0, 0)


def test_health_counts_scheduled_retries_and_dead_letters() -> None:
    queue = make_queue()
    queue.enqueue("work", {}, key="a")
    queue.enqueue("work", {}, key="b", delay=timedelta(hours=1))

    health = queue.health()
    assert (health.depth, health.scheduled) == (1, 1)

    run_until_settled(queue, registry_of(work=failing_always))
    assert queue.health().dead_letters == 2
