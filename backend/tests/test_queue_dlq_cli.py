"""The dead-letter command line and the in-memory queue."""

from collections.abc import Mapping
from typing import Any

import pytest

from sanket.queue.base import EnqueueResult, TaskContext, TaskRegistry
from sanket.queue.dlq import describe, parse_args, run
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.rq_queue import RqTaskQueue, job_id_for
from tests.queue_helpers import make_queue, registry_of, run_until_settled


def always_fails(payload: Mapping[str, Any], context: TaskContext) -> None:
    raise RuntimeError("provider quota exceeded")


def queue_with_two_dead_letters() -> RqTaskQueue:
    queue = make_queue()
    queue.enqueue("work", {"profile_id": 1}, key="one")
    queue.enqueue("work", {"profile_id": 2}, key="two")
    run_until_settled(queue, registry_of(work=always_fails))
    return queue


def run_cli(queue: RqTaskQueue, *argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    return run(parse_args(list(argv)), queue, lines.append), lines


def test_list_shows_task_key_attempts_error_and_payload() -> None:
    queue = queue_with_two_dead_letters()

    code, lines = run_cli(queue, "list")

    assert code == 0
    assert lines[-1] == "2 dead letters"
    row = next(line for line in lines if "key=one" in line)
    assert "task=work" in row
    assert "attempts=3" in row
    assert "provider quota exceeded" in row
    assert '"profile_id":1' in row


def test_a_long_payload_is_cut_in_the_listing() -> None:
    queue = make_queue()
    queue.enqueue("work", {"text": "x" * 1000}, key="big")
    run_until_settled(queue, registry_of(work=always_fails))

    [letter] = queue.list_dead_letters()

    assert len(describe(letter)) < 600
    assert describe(letter).count("x") <= 130


def test_requeue_by_id_queues_a_fresh_task_and_drops_the_dead_letter() -> None:
    queue = queue_with_two_dead_letters()

    code, lines = run_cli(queue, "requeue", job_id_for("work", "one"))

    assert code == 0
    assert lines == [f"{job_id_for('work', 'one')}: enqueued"]
    assert queue.health().depth == 1
    assert [letter.key for letter in queue.list_dead_letters()] == ["two"]


def test_requeue_all_and_a_missing_id_is_reported_with_a_failing_exit_code() -> None:
    queue = queue_with_two_dead_letters()

    code, lines = run_cli(queue, "requeue", "--all")
    assert code == 0 and len(lines) == 2
    assert queue.health().depth == 2

    code, lines = run_cli(queue, "requeue", "work-gone")
    assert code == 1
    assert lines == ["work-gone: no such dead letter"]


def test_purge_by_id_and_all() -> None:
    queue = queue_with_two_dead_letters()

    _, lines = run_cli(queue, "purge", job_id_for("work", "one"))
    assert lines == ["purged 1 dead letters"]
    _, lines = run_cli(queue, "purge", "--all")
    assert lines == ["purged 1 dead letters"]
    assert queue.list_dead_letters() == []


@pytest.mark.parametrize("argv", [["purge"], ["requeue"], ["purge", "--all", "work-x"]])
def test_requeue_and_purge_need_ids_or_all_but_not_both(argv: list[str]) -> None:
    queue = queue_with_two_dead_letters()

    with pytest.raises(SystemExit):
        run_cli(queue, *argv)

    assert queue.health().dead_letters == 2


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


# --- in-memory queue ----------------------------------------------------------------------


def test_the_memory_queue_deduplicates_pending_keys_like_the_real_one() -> None:
    queue = InMemoryTaskQueue()

    assert queue.enqueue("a", {"n": 1}, key="k") is EnqueueResult.ENQUEUED
    assert queue.enqueue("a", {"n": 1}, key="k") is EnqueueResult.DUPLICATE
    assert queue.enqueue("a", {"n": 1}) is EnqueueResult.ENQUEUED
    assert queue.enqueue("b", {}, key="k") is EnqueueResult.ENQUEUED
    assert [t.task_name for t in queue.pending()] == ["a", "a", "b"]
    assert queue.health().depth == 3


def test_the_memory_queue_allows_a_key_again_once_taken() -> None:
    queue = InMemoryTaskQueue()
    queue.enqueue("a", {}, key="k")

    assert len(queue.take_all()) == 1
    assert queue.enqueue("a", {}, key="k") is EnqueueResult.ENQUEUED


def test_the_memory_queue_rejects_a_payload_that_is_not_json() -> None:
    with pytest.raises(TypeError):
        InMemoryTaskQueue().enqueue("a", {"bad": object()})


def test_the_memory_queue_runs_chained_tasks() -> None:
    queue = InMemoryTaskQueue()
    seen: list[str] = []
    registry = TaskRegistry()

    def first(payload: Mapping[str, Any], context: TaskContext) -> None:
        seen.append("first")
        queue.enqueue("second", {})

    registry.register("first", first)
    registry.register("second", lambda payload, context: seen.append("second"))
    queue.enqueue("first", {})

    assert queue.run_pending(registry) == 2
    assert seen == ["first", "second"]
