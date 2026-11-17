"""The worker process: which worker class, the registry it installs, a burst run on fakeredis."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from pydantic import SecretStr
from rq import SimpleWorker, Worker
from sqlalchemy import Engine

from sanket.config import Settings
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.queue import runner
from sanket.queue.base import TaskRegistry
from sanket.queue.config import config_from_settings
from sanket.queue.rq_queue import RqTaskQueue
from sanket.queue.tasks import TASK_EMBED_PROFILE, TASK_MATCH_JOB, TASK_MATCH_PROFILE
from sanket.worker import __main__ as cli
from sanket.worker.run import choose_worker_class, run_worker
from tests.match_helpers import add_profile, index_all, match_rows, seed_job

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test",
    redis_url=SecretStr("redis://127.0.0.1:6379/0"),
    gemini_api_key=None,
    queue_name="worker-test",
    embedding_model="fake-embedding",
    embedding_model_version="1",
    queue_max_attempts=2,
    match_min_cosine=0.0,
    match_min_score=0.0,
)


@pytest.fixture(autouse=True)
def _restore_registry() -> Iterator[None]:
    previous = runner._active_registry
    yield
    runner.set_registry(previous)


def test_a_forking_worker_is_used_on_linux_and_a_simple_one_on_windows() -> None:
    assert choose_worker_class(simple=False, platform="linux") is Worker
    assert choose_worker_class(simple=False, platform="darwin") is Worker
    assert choose_worker_class(simple=False, platform="win32") is SimpleWorker


def test_the_simple_flag_forces_the_simple_worker_everywhere() -> None:
    assert choose_worker_class(simple=True, platform="linux") is SimpleWorker


def test_a_burst_drains_the_queue_with_the_registry_it_installs(clean_db: Engine) -> None:
    connection = fakeredis.FakeStrictRedis()
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    profile = add_profile(clean_db, summary="backend engineer python postgresql apis")
    queue = RqTaskQueue(connection, config_from_settings(SETTINGS))
    queue.enqueue(TASK_MATCH_JOB, {"job_id": job_id, "embedding_hash": "h"}, key=f"{job_id}-h")

    run_worker(
        SETTINGS,
        burst=True,
        simple=True,
        connection=connection,
        embedder=FakeEmbeddingClient(),
        db_engine=clean_db,
    )

    assert [row["profile_id"] for row in match_rows(clean_db)] == [profile.id]
    health = queue.health()
    assert (health.depth, health.running, health.dead_letters) == (0, 0, 0)
    assert runner._active_registry is not None
    assert runner._active_registry.names() == sorted(
        [TASK_EMBED_PROFILE, TASK_MATCH_JOB, TASK_MATCH_PROFILE]
    )


def test_a_failing_task_is_dead_lettered_and_the_worker_carries_on(clean_db: Engine) -> None:
    connection = fakeredis.FakeStrictRedis()
    queue = RqTaskQueue(connection, config_from_settings(SETTINGS))
    queue.enqueue(TASK_MATCH_JOB, {"nope": 1}, key="bad")  # invalid payload: permanent failure
    queue.enqueue("no_such_task", {}, key="unknown")

    run_worker(SETTINGS, burst=True, simple=True, connection=connection, db_engine=clean_db)

    assert queue.health().dead_letters == 2
    assert queue.health().depth == 0


def test_a_burst_also_moves_due_retries_into_the_queue(clean_db: Engine) -> None:
    connection = fakeredis.FakeStrictRedis()
    queue = RqTaskQueue(connection, config_from_settings(SETTINGS))
    queue.enqueue(TASK_MATCH_JOB, {"job_id": 1, "embedding_hash": "h"}, delay=timedelta(seconds=1))
    assert queue.health().scheduled == 1 and queue.health().depth == 0

    # The scheduler step of a burst run enqueues what is due; nothing is due yet here.
    run_worker(SETTINGS, burst=True, simple=True, connection=connection, db_engine=clean_db)

    assert queue.health().scheduled == 1
    assert queue.promote_due(datetime.now(UTC) + timedelta(seconds=5)) == 1


def test_the_engine_pool_is_disposed_before_the_worker_starts(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_work(self: SimpleWorker, **kwargs: object) -> bool:
        calls.append("work")
        return True

    monkeypatch.setattr(SimpleWorker, "work", fake_work)
    monkeypatch.setattr(clean_db, "dispose", lambda *a, **k: calls.append("dispose"))

    run_worker(
        SETTINGS,
        burst=True,
        simple=True,
        connection=fakeredis.FakeStrictRedis(),
        db_engine=clean_db,
    )

    assert calls == ["dispose", "work"]


def test_the_worker_asks_for_the_scheduler(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_work(self: SimpleWorker, **kwargs: object) -> bool:
        seen.update(kwargs)
        return True

    monkeypatch.setattr(SimpleWorker, "work", fake_work)

    run_worker(
        SETTINGS,
        burst=False,
        simple=True,
        connection=fakeredis.FakeStrictRedis(),
        db_engine=clean_db,
    )

    assert seen["with_scheduler"] is True and seen["burst"] is False


def test_it_logs_clear_start_and_stop_lines(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="sanket.worker.run"):
        run_worker(
            SETTINGS,
            burst=True,
            simple=True,
            connection=fakeredis.FakeStrictRedis(),
            db_engine=clean_db,
        )

    text = caplog.text
    assert "worker starting" in text and "queue=worker-test" in text and "mode=simple" in text
    assert "burst=true" in text
    assert "worker stopped" in text


# --- the command ------------------------------------------------------------------------------


def test_the_arguments_default_to_a_long_running_worker() -> None:
    args = cli.parse_args([])

    assert (args.burst, args.simple) == (False, False)


def test_the_flags_are_parsed() -> None:
    args = cli.parse_args(["--burst", "--simple"])

    assert (args.burst, args.simple) == (True, True)


def test_without_redis_the_command_exits_with_a_useful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli, "settings", Settings(database_url=SETTINGS.database_url, redis_url=None)
    )

    with pytest.raises(SystemExit, match="REDIS_URL is not set"):
        cli.main(["--burst"])


def test_an_unreachable_redis_exits_with_a_useful_message_and_no_url() -> None:
    unreachable = Settings(
        database_url=SETTINGS.database_url,
        redis_url=SecretStr("redis://user:secret@127.0.0.1:1/0"),
        redis_timeout_seconds=0.2,
    )

    with pytest.raises(SystemExit) as excinfo:
        run_worker(unreachable, burst=True, simple=True)

    message = str(excinfo.value)
    assert "cannot reach Redis" in message and "secret" not in message


def test_the_registry_type_is_a_task_registry(clean_db: Engine) -> None:
    run_worker(
        SETTINGS,
        burst=True,
        simple=True,
        connection=fakeredis.FakeStrictRedis(),
        db_engine=clean_db,
    )

    assert isinstance(runner._active_registry, TaskRegistry)
