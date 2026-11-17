"""The task handlers of the matching pipeline, on the in-memory queue and on RQ with fakeredis."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, select

from sanket.config import Settings
from sanket.embeddings.client import EmbeddingError
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.matching.tasks import MatchTaskDeps, build_registry, registry_from_settings
from sanket.models import EmbeddingStatus, Profile
from sanket.profiles.service import create_profile
from sanket.queue.base import EnqueueResult, PermanentTaskError, TaskContext
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import (
    NO_EMBEDDING,
    TASK_EMBED_PROFILE,
    TASK_MATCH_JOB,
    TASK_MATCH_PROFILE,
    embed_profile_key,
    match_profile_key,
)
from tests.index_helpers import SPEC, set_posting_count
from tests.match_helpers import (
    RecordingNotifier,
    ScriptedQueryClient,
    add_profile,
    config,
    index_all,
    match_rows,
    profile_body,
    seed_job,
)
from tests.queue_helpers import make_queue, run_burst, run_until_settled

LENIENT = config(min_cosine=-1.0, min_score=0.0)
SUMMARY = "backend engineer python postgresql apis"


def context(task: str, attempt: int = 1, max_attempts: int = 3) -> TaskContext:
    return TaskContext(task, None, attempt, max_attempts)


def deps_for(engine: Engine, **overrides: Any) -> MatchTaskDeps:
    values: dict[str, Any] = {
        "cfg": LENIENT,
        "embedder": FakeEmbeddingClient(),
        "queue": InMemoryTaskQueue(),
        "notifier": RecordingNotifier(),
        "db_engine": engine,
    }
    values.update(overrides)
    return MatchTaskDeps(**values)


def run_handler(deps: MatchTaskDeps, task: str, payload: Mapping[str, Any], **ctx: int) -> None:
    build_registry(deps).get(task)(payload, context(task, **ctx))


def status_of(engine: Engine, profile_id: int) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                select(Profile.embedding_status).where(Profile.id == profile_id)
            ).scalar_one()
        )


# --- the registry -----------------------------------------------------------------------------


def test_the_registry_has_the_three_pipeline_tasks(clean_db: Engine) -> None:
    assert build_registry(deps_for(clean_db)).names() == sorted(
        [TASK_EMBED_PROFILE, TASK_MATCH_JOB, TASK_MATCH_PROFILE]
    )


def test_the_registry_is_built_from_settings_with_everything_injectable(
    clean_db: Engine,
) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test", gemini_api_key=None
    )
    notifier = RecordingNotifier()

    registry = registry_from_settings(
        settings,
        queue=InMemoryTaskQueue(),
        embedder=FakeEmbeddingClient(),
        notifier=notifier,
        db_engine=clean_db,
    )

    assert registry.names() == sorted([TASK_EMBED_PROFILE, TASK_MATCH_JOB, TASK_MATCH_PROFILE])


def test_without_an_api_key_the_embedding_task_fails_permanently(clean_db: Engine) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test", gemini_api_key=None
    )
    registry = registry_from_settings(settings, queue=None, db_engine=clean_db)
    profile = add_profile(clean_db, embed=False)

    with pytest.raises(PermanentTaskError, match="GEMINI_API_KEY"):
        registry.get(TASK_EMBED_PROFILE)(
            {"profile_id": profile.id, "content_hash": profile.content_hash},
            context(TASK_EMBED_PROFILE),
        )


# --- payload validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task", "payload"),
    [
        (TASK_EMBED_PROFILE, {}),
        (TASK_EMBED_PROFILE, {"profile_id": 0, "content_hash": "h"}),
        (TASK_EMBED_PROFILE, {"profile_id": 1, "content_hash": "h", "extra": 1}),
        (TASK_MATCH_JOB, {"job_id": "abc", "embedding_hash": "h"}),
        (TASK_MATCH_JOB, {"job_id": 1}),
        (TASK_MATCH_PROFILE, {"profile_id": 1, "content_hash": "h"}),
        (TASK_MATCH_PROFILE, {"profile_id": -3, "content_hash": "h", "embedding_hash": "e"}),
    ],
)
def test_an_invalid_payload_is_a_permanent_error(
    clean_db: Engine, task: str, payload: Mapping[str, Any]
) -> None:
    with pytest.raises(PermanentTaskError, match="invalid"):
        run_handler(deps_for(clean_db), task, payload)


# --- embed_profile ----------------------------------------------------------------------------


def embed_payload(profile_id: int, content_hash: str) -> dict[str, Any]:
    return {"profile_id": profile_id, "content_hash": content_hash}


def test_embedding_a_profile_marks_it_ready_and_queues_the_match(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    queue = InMemoryTaskQueue()

    run_handler(
        deps_for(clean_db, queue=queue),
        TASK_EMBED_PROFILE,
        embed_payload(profile.id, profile.content_hash),
    )

    assert status_of(clean_db, profile.id) == EmbeddingStatus.READY
    [task] = queue.enqueued
    assert task.task_name == TASK_MATCH_PROFILE
    embedding_hash = task.payload["embedding_hash"]
    assert task.payload == {
        "profile_id": profile.id,
        "content_hash": profile.content_hash,
        "embedding_hash": embedding_hash,
    }
    assert task.key == match_profile_key(profile.id, profile.content_hash, embedding_hash)


def test_an_already_embedded_profile_still_queues_the_match_with_the_same_key(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)
    queue = InMemoryTaskQueue()
    deps = deps_for(clean_db, queue=queue)
    payload = embed_payload(profile.id, profile.content_hash)

    run_handler(deps, TASK_EMBED_PROFILE, payload)
    embedder = deps.embedder
    assert isinstance(embedder, FakeEmbeddingClient)
    calls = len(embedder.query_calls)
    first_key = queue.take_all()[0].key
    run_handler(deps, TASK_EMBED_PROFILE, payload)

    assert len(embedder.query_calls) == calls  # the hash gate: no second provider call
    [again] = queue.enqueued[1:]
    assert again.key == first_key


def test_a_deleted_profile_is_a_clean_no_op(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()

    run_handler(deps_for(clean_db, queue=queue), TASK_EMBED_PROFILE, embed_payload(42, "h"))

    assert queue.enqueued == []


def test_a_retryable_embedding_error_propagates_so_the_queue_retries(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    embedder = ScriptedQueryClient(error=EmbeddingError("quota", retryable=True))
    queue = InMemoryTaskQueue()

    with pytest.raises(EmbeddingError):
        run_handler(
            deps_for(clean_db, embedder=embedder, queue=queue),
            TASK_EMBED_PROFILE,
            embed_payload(profile.id, profile.content_hash),
            attempt=1,
            max_attempts=3,
        )

    assert status_of(clean_db, profile.id) == EmbeddingStatus.PENDING
    assert queue.enqueued == []


def test_the_final_attempt_records_the_profile_as_failed(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    embedder = ScriptedQueryClient(error=EmbeddingError("quota", retryable=True))

    with pytest.raises(EmbeddingError):
        run_handler(
            deps_for(clean_db, embedder=embedder),
            TASK_EMBED_PROFILE,
            embed_payload(profile.id, profile.content_hash),
            attempt=3,
            max_attempts=3,
        )

    assert status_of(clean_db, profile.id) == EmbeddingStatus.FAILED


def test_a_rejected_input_is_a_permanent_error(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    embedder = ScriptedQueryClient(error=EmbeddingError("bad text", retryable=False))
    queue = InMemoryTaskQueue()

    with pytest.raises(PermanentTaskError, match="bad text"):
        run_handler(
            deps_for(clean_db, embedder=embedder, queue=queue),
            TASK_EMBED_PROFILE,
            embed_payload(profile.id, profile.content_hash),
        )

    assert status_of(clean_db, profile.id) == EmbeddingStatus.FAILED
    assert queue.enqueued == []


def test_without_a_queue_embedding_still_works(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)

    run_handler(
        deps_for(clean_db, queue=None),
        TASK_EMBED_PROFILE,
        embed_payload(profile.id, profile.content_hash),
    )

    assert status_of(clean_db, profile.id) == EmbeddingStatus.READY


def test_a_queue_failure_after_embedding_propagates_and_the_retry_repeats_nothing(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)

    class BrokenQueue(InMemoryTaskQueue):
        def enqueue(self, *args: Any, **kwargs: Any) -> EnqueueResult:
            raise ConnectionError("redis down")

    embedder = FakeEmbeddingClient()
    payload = embed_payload(profile.id, profile.content_hash)
    with pytest.raises(ConnectionError):
        run_handler(
            deps_for(clean_db, embedder=embedder, queue=BrokenQueue()), TASK_EMBED_PROFILE, payload
        )
    calls = len(embedder.query_calls)

    run_handler(deps_for(clean_db, embedder=embedder), TASK_EMBED_PROFILE, payload)

    assert len(embedder.query_calls) == calls
    assert status_of(clean_db, profile.id) == EmbeddingStatus.READY


# --- match_job and match_profile --------------------------------------------------------------


def test_the_match_job_handler_matches_and_is_idempotent(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    notifier = RecordingNotifier()
    deps = deps_for(clean_db, notifier=notifier)
    payload = {"job_id": job_id, "embedding_hash": "whatever-the-key-says"}

    run_handler(deps, TASK_MATCH_JOB, payload)
    before = match_rows(clean_db)
    run_handler(deps, TASK_MATCH_JOB, payload)

    assert len(before) == 1 and match_rows(clean_db) == before
    assert len(notifier.records) == 1


def test_the_match_job_handler_withdraws_for_the_no_embedding_marker(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    deps = deps_for(clean_db)
    run_handler(deps, TASK_MATCH_JOB, {"job_id": job_id, "embedding_hash": "h"})
    set_posting_count(clean_db, job_id, 0)

    run_handler(deps, TASK_MATCH_JOB, {"job_id": job_id, "embedding_hash": NO_EMBEDDING})

    assert [row["status"] for row in match_rows(clean_db)] == ["withdrawn"]


def test_the_match_profile_handler_matches_and_is_idempotent(clean_db: Engine) -> None:
    seed_job(clean_db, title="Backend Engineer", published_at=datetime.now(UTC))
    index_all(clean_db)
    profile = add_profile(clean_db, summary=SUMMARY)
    notifier = RecordingNotifier()
    deps = deps_for(clean_db, notifier=notifier)
    payload = {
        "profile_id": profile.id,
        "content_hash": profile.content_hash,
        "embedding_hash": "e",
    }

    run_handler(deps, TASK_MATCH_PROFILE, payload)
    before = match_rows(clean_db)
    run_handler(deps, TASK_MATCH_PROFILE, payload)

    assert len(before) == 1 and match_rows(clean_db) == before
    assert len(notifier.records) == 1


def test_the_default_notifier_does_nothing_but_the_match_is_stored(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)
    add_profile(clean_db, summary=SUMMARY)
    registry = build_registry(MatchTaskDeps(cfg=LENIENT, db_engine=clean_db))

    registry.get(TASK_MATCH_JOB)({"job_id": job_id, "embedding_hash": "h"}, context(TASK_MATCH_JOB))

    assert len(match_rows(clean_db)) == 1


# --- the whole chain --------------------------------------------------------------------------


def test_a_saved_profile_is_embedded_and_matched_through_the_in_memory_queue(
    clean_db: Engine,
) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    queue = InMemoryTaskQueue()
    notifier = RecordingNotifier()
    saved = create_profile(
        "owner-1",
        profile_body(summary=SUMMARY),
        queue=queue,
        max_profiles=10,
        db_engine=clean_db,
    )
    profile = saved.profile
    assert [t.task_name for t in queue.pending()] == [TASK_EMBED_PROFILE]
    assert queue.pending()[0].key == embed_profile_key(profile.id, profile.content_hash)

    deps = deps_for(clean_db, queue=queue, notifier=notifier)
    ran = queue.run_pending(build_registry(deps))

    assert ran == 2
    assert status_of(clean_db, profile.id) == EmbeddingStatus.READY
    [row] = match_rows(clean_db)
    assert row["job_id"] == job_id and row["profile_id"] == profile.id
    assert [r.job_id for r in notifier.records] == [job_id]


# --- on RQ with fakeredis ---------------------------------------------------------------------


def test_a_saved_profile_is_embedded_and_matched_by_a_worker_on_rq(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    queue = make_queue()
    notifier = RecordingNotifier()
    saved = create_profile(
        "owner-1",
        profile_body(summary=SUMMARY),
        queue=queue,
        max_profiles=10,
        db_engine=clean_db,
    )
    registry = build_registry(deps_for(clean_db, queue=queue, notifier=notifier))

    run_burst(queue, registry)  # embed_profile, which queues match_profile
    run_burst(queue, registry)  # match_profile

    assert status_of(clean_db, saved.profile.id) == EmbeddingStatus.READY
    assert [row["job_id"] for row in match_rows(clean_db)] == [job_id]
    assert len(notifier.records) == 1
    health = queue.health()
    assert (health.depth, health.dead_letters) == (0, 0)


def test_a_quota_error_is_retried_by_the_queue_until_it_succeeds(clean_db: Engine) -> None:
    seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    queue = make_queue()
    failures = {"left": 1}

    class FlakyEmbedder(FakeEmbeddingClient):
        def embed_query(self, text: str) -> list[float]:
            if failures["left"] > 0:
                failures["left"] -= 1
                raise EmbeddingError("quota exceeded", retryable=True)
            return super().embed_query(text)

    embedder = FlakyEmbedder(model_name=SPEC.model_name, model_version=SPEC.model_version)
    saved = create_profile(
        "owner-1", profile_body(summary=SUMMARY), queue=queue, max_profiles=10, db_engine=clean_db
    )
    registry = build_registry(deps_for(clean_db, queue=queue, embedder=embedder))

    run_until_settled(queue, registry)

    assert failures["left"] == 0
    assert status_of(clean_db, saved.profile.id) == EmbeddingStatus.READY
    assert len(match_rows(clean_db)) == 1
    assert queue.health().dead_letters == 0


def test_an_embedding_that_always_fails_ends_as_a_dead_letter_and_a_failed_profile(
    clean_db: Engine,
) -> None:
    queue = make_queue()
    embedder = ScriptedQueryClient(error=EmbeddingError("quota exceeded", retryable=True))
    saved = create_profile(
        "owner-1", profile_body(summary=SUMMARY), queue=queue, max_profiles=10, db_engine=clean_db
    )
    registry = build_registry(deps_for(clean_db, queue=queue, embedder=embedder))

    run_until_settled(queue, registry)

    assert status_of(clean_db, saved.profile.id) == EmbeddingStatus.FAILED
    [letter] = queue.list_dead_letters()
    assert letter.task_name == TASK_EMBED_PROFILE and "quota" in letter.error
