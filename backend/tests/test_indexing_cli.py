import logging
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine

from sanket.config import settings
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing import __main__ as cli
from sanket.indexing.service import IndexSummary, index_pending
from sanket.matching.triggers import index_observer
from sanket.queue.base import EnqueueResult
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import TASK_MATCH_JOB
from tests.index_helpers import SPEC, add_indexable_job


def test_default_is_a_dry_run() -> None:
    args = cli.parse_args([])

    assert (args.apply, args.dry_run, args.limit, args.batch_size) == (False, False, None, None)


def test_apply_limit_and_batch_size_are_parsed() -> None:
    args = cli.parse_args(["--apply", "--limit", "5", "--batch-size", "7"])

    assert (args.apply, args.limit, args.batch_size) == (True, 5, 7)


def test_apply_and_dry_run_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--apply", "--dry-run"])


def test_limit_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--limit", "0"])


def test_dry_run_needs_no_api_key_and_passes_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_index(cfg, client, *, limit, apply, on_changes):
        seen.update(client=client, limit=limit, apply=apply, on_changes=on_changes)
        return IndexSummary()

    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_pending", fake_index)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    cli.main([])

    assert seen == {"client": None, "limit": None, "apply": False, "on_changes": None}


def test_apply_without_an_api_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        cli.main(["--apply"])


def test_failed_jobs_make_the_command_exit_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_pending", lambda *a, **k: IndexSummary(failed=2))

    with pytest.raises(SystemExit, match="2 jobs failed"):
        cli.main([])


def test_summary_line_lists_every_counter() -> None:
    line = IndexSummary(scanned=3, embedded=2, applied=True).line("m")

    for key in (
        "mode=apply",
        "model=m",
        "scanned=3",
        "tsvector_updated=0",
        "embedded=2",
        "unchanged=0",
        "removed=0",
        "skipped_no_text=0",
        "failed=0",
    ):
        assert key in line


# --- queueing matching after an applied run -----------------------------------------------


def _wire_apply(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, observer: Callable | None
) -> list[IndexSummary]:
    """Run `main --apply` against the test database with the fake embedding client."""
    summaries: list[IndexSummary] = []

    def real_index(cfg, client, *, limit, apply, on_changes=None):
        summary = index_pending(
            cfg, client, limit=limit, apply=apply, db_engine=engine, on_changes=on_changes
        )
        summaries.append(summary)
        return summary

    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_pending", real_index)
    monkeypatch.setattr(cli, "GeminiEmbeddingClient", lambda *a, **k: _fake_client(k, a))
    monkeypatch.setattr(cli, "index_observer_from_settings", lambda config: observer)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("not-a-real-key"))
    monkeypatch.setattr(settings, "embedding_model", SPEC.model_name)
    monkeypatch.setattr(settings, "embedding_model_version", SPEC.model_version)
    monkeypatch.setattr(settings, "embedding_dimensions", SPEC.dimensions)
    return summaries


def _fake_client(kwargs: dict, args: tuple) -> FakeEmbeddingClient:
    return FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)


def test_an_applied_run_queues_matching_for_the_jobs_it_embedded(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = add_indexable_job(clean_db)
    queue = InMemoryTaskQueue()
    _wire_apply(monkeypatch, clean_db, index_observer(settings, queue))

    cli.main(["--apply"])

    [task] = queue.enqueued
    assert task.task_name == TASK_MATCH_JOB and task.payload["job_id"] == job_id


def test_a_failing_queue_changes_neither_the_exit_code_nor_the_summary_line(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    add_indexable_job(clean_db)

    class DownQueue(InMemoryTaskQueue):
        def enqueue(self, *args: Any, **kwargs: Any) -> EnqueueResult:
            raise ConnectionError("redis down")

    summaries = _wire_apply(monkeypatch, clean_db, index_observer(settings, DownQueue()))

    with caplog.at_level(logging.INFO):
        cli.main(["--apply"])  # must not raise SystemExit

    [summary] = summaries
    assert summary.embedded == 1 and summary.failed == 0
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("indexing mode")]
    assert lines == [summary.line(settings.embedding_model)]
    assert "Queueing matching tasks failed" in caplog.text


def test_a_dry_run_never_builds_an_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(config: Any) -> None:
        raise AssertionError("no queue for a dry run")

    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_observer_from_settings", explode)
    monkeypatch.setattr(cli, "index_pending", lambda *a, **k: IndexSummary())

    cli.main([])
