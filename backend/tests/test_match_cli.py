"""`python -m sanket.matching`: parsing, the work it derives, dry run, queueing and inline."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text, update

from sanket.config import Settings
from sanket.embeddings.client import EmbeddingError
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.matching import __main__ as cli
from sanket.matching.__main__ import CliContext, execute, parse_args, select_work
from sanket.matching.work import job_work, profile_work
from sanket.models import EmbeddingStatus, JobEmbedding, Profile
from sanket.queue.base import EnqueueResult
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import (
    NO_EMBEDDING,
    TASK_EMBED_PROFILE,
    TASK_MATCH_JOB,
    TASK_MATCH_PROFILE,
)
from tests.index_helpers import SPEC, set_posting_count
from tests.match_helpers import (
    RecordingNotifier,
    ScriptedQueryClient,
    add_profile,
    index_all,
    match_rows,
    seed_job,
    status_of,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
SUMMARY = "backend engineer python postgresql apis"
SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test",
    gemini_api_key=None,
    embedding_model=SPEC.model_name,
    embedding_model_version=SPEC.model_version,
    embedding_dimensions=SPEC.dimensions,
    match_min_cosine=0.0,
    match_min_score=0.0,
)


def context(engine: Engine, **overrides: Any) -> CliContext:
    values: dict[str, Any] = {
        "config": SETTINGS,
        "queue": InMemoryTaskQueue(),
        "embedder": FakeEmbeddingClient(),
        "db_engine": engine,
        "now": NOW,
    }
    values.update(overrides)
    return CliContext(**values)


def run(argv: list[str], engine: Engine, **overrides: Any) -> int:
    return execute(parse_args(argv), context(engine, **overrides))


# --- parsing ----------------------------------------------------------------------------------


def test_embed_profiles_is_a_dry_run_unless_applied() -> None:
    args = parse_args(["embed-profiles"])

    assert (args.command, args.apply, args.inline, args.limit) == (
        "embed-profiles",
        False,
        False,
        1000,
    )


def test_the_flags_of_embed_profiles_are_parsed() -> None:
    args = parse_args(["embed-profiles", "--apply", "--inline", "--limit", "5"])

    assert (args.apply, args.inline, args.limit) == (True, True, 5)


def test_rematch_takes_a_job_a_profile_or_everything() -> None:
    assert parse_args(["rematch", "--job", "7"]).job == 7
    assert parse_args(["rematch", "--profile", "3"]).profile == 3
    both = parse_args(["rematch", "--all-jobs", "--all-profiles", "--since-days", "2"])
    assert (both.all_jobs, both.all_profiles, both.since_days) == (True, True, 2)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["rematch"],
        ["rematch", "--job", "1", "--profile", "2"],
        ["rematch", "--job", "1", "--all-jobs"],
        ["rematch", "--profile", "1", "--all-profiles"],
        ["rematch", "--job", "1", "--since-days", "3"],
        ["rematch", "--job", "0"],
        ["rematch", "--all-jobs", "--since-days", "0"],
        ["embed-profiles", "--limit", "0"],
        ["frobnicate"],
    ],
)
def test_invalid_arguments_exit(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)


# --- the work it derives ----------------------------------------------------------------------


def test_embed_work_is_the_profiles_that_are_not_ready(clean_db: Engine) -> None:
    pending = add_profile(clean_db, name="Pending", embed=False)
    failed = add_profile(clean_db, name="Failed", embed=False)
    add_profile(clean_db, name="Ready")
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == failed.id)
            .values(embedding_status=EmbeddingStatus.FAILED)
        )

    items = select_work(parse_args(["embed-profiles"]), context(clean_db))

    assert [(i.task_name, i.payload["profile_id"]) for i in items] == [
        (TASK_EMBED_PROFILE, pending.id),
        (TASK_EMBED_PROFILE, failed.id),
    ]
    assert items[0].payload["content_hash"] == pending.content_hash


def test_embed_work_respects_the_limit(clean_db: Engine) -> None:
    for number in range(3):
        add_profile(clean_db, name=f"P{number}", embed=False)

    items = select_work(parse_args(["embed-profiles", "--limit", "2"]), context(clean_db))

    assert len(items) == 2


def test_all_jobs_work_is_the_live_jobs_plus_dead_jobs_still_holding_matches(
    clean_db: Engine,
) -> None:
    live = seed_job(clean_db, title="Backend Engineer")
    dead = seed_job(clean_db, title="Backend Engineer Two")
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    run(["rematch", "--all-jobs", "--apply", "--inline"], clean_db)
    set_posting_count(clean_db, dead, 0)

    items = select_work(parse_args(["rematch", "--all-jobs"]), context(clean_db))

    by_job = {i.payload["job_id"]: i.payload["embedding_hash"] for i in items}
    assert set(by_job) == {live, dead}
    assert by_job[dead] == NO_EMBEDDING and by_job[live] != NO_EMBEDDING
    assert all(i.task_name == TASK_MATCH_JOB for i in items)


def test_since_days_limits_jobs_to_those_whose_embedding_changed(clean_db: Engine) -> None:
    old = seed_job(clean_db, title="Backend Engineer")
    new = seed_job(clean_db, title="Backend Engineer Two")
    index_all(clean_db)
    with clean_db.begin() as conn:
        conn.execute(
            update(JobEmbedding)
            .where(JobEmbedding.job_id == old)
            .values(updated_at=NOW - timedelta(days=30))
        )
        conn.execute(
            update(JobEmbedding)
            .where(JobEmbedding.job_id == new)
            .values(updated_at=NOW - timedelta(days=1))
        )

    items = select_work(
        parse_args(["rematch", "--all-jobs", "--since-days", "7"]), context(clean_db)
    )

    assert [i.payload["job_id"] for i in items] == [new]


def test_a_single_job_gives_one_task_and_an_unknown_job_is_an_error(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)

    [item] = select_work(parse_args(["rematch", "--job", str(job_id)]), context(clean_db))

    assert item.payload["job_id"] == job_id and item.payload["embedding_hash"] != NO_EMBEDDING
    with pytest.raises(SystemExit, match="does not exist"):
        select_work(parse_args(["rematch", "--job", "999"]), context(clean_db))


def test_a_dead_single_job_gives_a_withdrawing_task(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)
    set_posting_count(clean_db, job_id, 0)

    [item] = select_work(parse_args(["rematch", "--job", str(job_id)]), context(clean_db))

    assert item.payload["embedding_hash"] == NO_EMBEDDING


def test_profile_work_covers_embedded_profiles_and_switched_off_ones(clean_db: Engine) -> None:
    ready = add_profile(clean_db, name="Ready")
    off = add_profile(clean_db, name="Off", active=False, embed=False)
    add_profile(clean_db, name="Pending", embed=False)

    with clean_db.connect() as conn:
        items = profile_work(conn, SPEC)

    by_profile = {i.payload["profile_id"]: i for i in items}
    assert set(by_profile) == {ready.id, off.id}
    assert by_profile[ready.id].task_name == TASK_MATCH_PROFILE
    assert by_profile[ready.id].payload["embedding_hash"] != NO_EMBEDDING
    assert by_profile[off.id].payload["embedding_hash"] == NO_EMBEDDING


def test_a_single_profile_must_exist_and_be_embedded(clean_db: Engine) -> None:
    pending = add_profile(clean_db, embed=False)

    with pytest.raises(SystemExit, match="not embedded"):
        select_work(parse_args(["rematch", "--profile", str(pending.id)]), context(clean_db))


def test_since_days_limits_profiles_to_those_saved_recently(clean_db: Engine) -> None:
    stale = add_profile(clean_db, name="Stale")
    fresh = add_profile(clean_db, name="Fresh")
    with clean_db.begin() as conn:
        conn.execute(
            text("update profile set updated_at = :old where id = :id"),
            {"old": NOW - timedelta(days=30), "id": stale.id},
        )
        conn.execute(
            text("update profile set updated_at = :recent where id = :id"),
            {"recent": NOW - timedelta(days=1), "id": fresh.id},
        )

    items = select_work(
        parse_args(["rematch", "--all-profiles", "--since-days", "7"]), context(clean_db)
    )

    assert [i.payload["profile_id"] for i in items] == [fresh.id]


# --- dry run ----------------------------------------------------------------------------------


def test_a_dry_run_counts_and_lists_but_queues_and_runs_nothing(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    profile = add_profile(clean_db, embed=False)
    queue = InMemoryTaskQueue()
    embedder = FakeEmbeddingClient()

    with caplog.at_level(logging.INFO):
        code = run(["embed-profiles"], clean_db, queue=queue, embedder=embedder)

    assert code == 0
    assert queue.enqueued == [] and embedder.query_calls == []
    assert status_of(clean_db, profile.id) == EmbeddingStatus.PENDING
    assert "embed-profiles mode=dry-run selected=1 queued=0" in caplog.text
    assert "dry run: nothing was done" in caplog.text


def test_a_dry_run_needs_neither_queue_nor_key(clean_db: Engine) -> None:
    add_profile(clean_db, embed=False)

    assert run(["embed-profiles"], clean_db, queue=None, embedder=None) == 0


def test_inline_without_apply_is_still_a_dry_run(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)

    assert run(["embed-profiles", "--inline"], clean_db) == 0
    assert status_of(clean_db, profile.id) == EmbeddingStatus.PENDING


# --- queueing ---------------------------------------------------------------------------------


def test_apply_queues_the_derived_tasks_and_a_second_apply_finds_them_pending(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    profile = add_profile(clean_db, embed=False)
    queue = InMemoryTaskQueue()

    with caplog.at_level(logging.INFO):
        first = run(["embed-profiles", "--apply"], clean_db, queue=queue)
        second = run(["embed-profiles", "--apply"], clean_db, queue=queue)

    assert (first, second) == (0, 0)
    [task] = queue.enqueued
    assert task.task_name == TASK_EMBED_PROFILE and task.payload["profile_id"] == profile.id
    assert "mode=apply-queue selected=1 queued=1 duplicate=0" in caplog.text
    assert "mode=apply-queue selected=1 queued=0 duplicate=1" in caplog.text


def test_apply_without_a_queue_exits_and_points_at_inline(clean_db: Engine) -> None:
    add_profile(clean_db, embed=False)

    with pytest.raises(SystemExit, match="REDIS_URL is not set.*--inline"):
        run(["embed-profiles", "--apply"], clean_db, queue=None)


class DownQueue(InMemoryTaskQueue):
    def enqueue(self, *args: Any, **kwargs: Any) -> EnqueueResult:
        raise ConnectionError("redis down")


def test_a_queue_failure_gives_a_non_zero_exit(clean_db: Engine) -> None:
    add_profile(clean_db, embed=False)

    assert run(["embed-profiles", "--apply"], clean_db, queue=DownQueue()) == 1


def test_rematch_queues_match_tasks(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    queue = InMemoryTaskQueue()

    run(["rematch", "--all-jobs", "--all-profiles", "--apply"], clean_db, queue=queue)

    assert sorted(t.task_name for t in queue.enqueued) == [TASK_MATCH_JOB, TASK_MATCH_PROFILE]
    assert [t.payload["job_id"] for t in queue.pending(TASK_MATCH_JOB)] == [job_id]


# --- inline -----------------------------------------------------------------------------------


def test_inline_embeds_pending_profiles_and_matches_them(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    profile = add_profile(clean_db, summary=SUMMARY, embed=False)

    code = run(["embed-profiles", "--apply", "--inline"], clean_db, queue=None)

    assert code == 0
    assert status_of(clean_db, profile.id) == EmbeddingStatus.READY
    assert [(r["job_id"], r["profile_id"]) for r in match_rows(clean_db)] == [(job_id, profile.id)]


def test_inline_embedding_needs_the_api_key(clean_db: Engine) -> None:
    add_profile(clean_db, embed=False)

    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        run(["embed-profiles", "--apply", "--inline"], clean_db, embedder=None)


def test_inline_with_nothing_to_embed_needs_no_key(clean_db: Engine) -> None:
    assert run(["embed-profiles", "--apply", "--inline"], clean_db, embedder=None) == 0


def test_an_inline_failure_gives_a_non_zero_exit_and_the_others_still_run(
    clean_db: Engine,
) -> None:
    bad = add_profile(clean_db, name="Bad", summary="poison", embed=False)
    good = add_profile(clean_db, name="Good", summary=SUMMARY, embed=False)

    class PickyEmbedder(ScriptedQueryClient):
        def embed_query(self, text: str) -> list[float]:
            if "poison" in text:
                raise EmbeddingError("rejected", retryable=False)
            return FakeEmbeddingClient.embed_query(self, text)

    code = run(["embed-profiles", "--apply", "--inline"], clean_db, embedder=PickyEmbedder())

    assert code == 1
    assert status_of(clean_db, bad.id) == EmbeddingStatus.FAILED
    assert status_of(clean_db, good.id) == EmbeddingStatus.READY


def test_inline_rematch_runs_the_matching_without_an_api_key(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    profile = add_profile(clean_db, summary=SUMMARY)

    code = run(["rematch", "--job", str(job_id), "--apply", "--inline"], clean_db, embedder=None)

    assert code == 0
    assert [(r["job_id"], r["profile_id"]) for r in match_rows(clean_db)] == [(job_id, profile.id)]


def test_rematching_a_dead_job_inline_withdraws_its_matches(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    run(["rematch", "--all-jobs", "--apply", "--inline"], clean_db)
    set_posting_count(clean_db, job_id, 0)

    assert run(["rematch", "--all-jobs", "--apply", "--inline"], clean_db) == 0

    assert [r["status"] for r in match_rows(clean_db)] == ["withdrawn"]


def test_main_builds_its_context_from_the_settings_and_exits_with_the_code(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_profile(clean_db, embed=False)
    monkeypatch.setattr(cli, "settings", SETTINGS)
    monkeypatch.setattr(cli, "engine", clean_db)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["embed-profiles"])

    assert excinfo.value.code == 0


def test_job_work_helper_is_empty_without_jobs(clean_db: Engine) -> None:
    with clean_db.connect() as conn:
        assert job_work(conn, SPEC) == []


def test_an_inline_run_announces_new_matches_to_the_notifier_of_the_context(
    clean_db: Engine,
) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    notifier = RecordingNotifier()

    run(["rematch", "--all-jobs", "--apply", "--inline"], clean_db, notifier=notifier)

    assert [record.job_id for record in notifier.records] == [job_id]
