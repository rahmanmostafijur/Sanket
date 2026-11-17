"""The indexing run reports what it changed to an optional observer, after the writes."""

import logging
from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from sanket.embeddings.client import EmbeddingError
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.service import IndexChanges, index_jobs, index_pending
from sanket.models import JobEmbedding
from tests.index_helpers import (
    CFG,
    SPEC,
    add_indexable_job,
    embeddings_of,
    set_posting_count,
)


def fake() -> FakeEmbeddingClient:
    return FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)


class Observer:
    def __init__(self) -> None:
        self.calls: list[IndexChanges] = []

    def __call__(self, changes: IndexChanges) -> None:
        self.calls.append(changes)


def stored_hash(engine: Engine, job_id: int) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                select(JobEmbedding.content_hash).where(JobEmbedding.job_id == job_id)
            ).scalar_one()
        )


def test_the_observer_gets_the_embedded_jobs_with_the_hash_that_was_stored(
    clean_db: Engine,
) -> None:
    first = add_indexable_job(clean_db)
    second = add_indexable_job(clean_db, title="Data Analyst")
    observer = Observer()

    index_pending(CFG, fake(), apply=True, db_engine=clean_db, on_changes=observer)

    [changes] = observer.calls
    assert dict(changes.embedded) == {
        first: stored_hash(clean_db, first),
        second: stored_hash(clean_db, second),
    }
    assert changes.removed == ()


def test_the_observer_gets_the_jobs_removed_as_dead(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    index_pending(CFG, fake(), apply=True, db_engine=clean_db)
    set_posting_count(clean_db, job_id, 0)
    observer = Observer()

    index_pending(CFG, fake(), apply=True, db_engine=clean_db, on_changes=observer)

    [changes] = observer.calls
    assert changes.removed == (job_id,) and changes.embedded == ()
    assert embeddings_of(clean_db, job_id) == {}


def test_a_dry_run_reports_nothing(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    observer = Observer()

    index_pending(CFG, None, apply=False, db_engine=clean_db, on_changes=observer)

    assert observer.calls == []


def test_a_run_that_changed_nothing_reports_nothing(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    index_pending(CFG, fake(), apply=True, db_engine=clean_db)
    observer = Observer()

    index_pending(CFG, fake(), apply=True, db_engine=clean_db, on_changes=observer)

    assert observer.calls == []


def test_a_job_whose_embedding_failed_is_not_reported(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    observer = Observer()
    client = FakeEmbeddingClient(
        model_name=SPEC.model_name,
        model_version=SPEC.model_version,
        fail_when=lambda texts: EmbeddingError("quota", retryable=True),
    )

    summary = index_pending(CFG, client, apply=True, db_engine=clean_db, on_changes=observer)

    assert summary.failed == 1 and observer.calls == []


def test_index_jobs_reports_too(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    observer = Observer()

    index_jobs([job_id], CFG, fake(), clean_db, on_changes=observer)

    [changes] = observer.calls
    assert dict(changes.embedded) == {job_id: stored_hash(clean_db, job_id)}


def test_an_observer_that_raises_changes_neither_the_summary_nor_the_stored_result(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    job_id = add_indexable_job(clean_db)

    def broken(changes: IndexChanges) -> None:
        raise ConnectionError("redis is down")

    with caplog.at_level(logging.ERROR):
        summary = index_pending(CFG, fake(), apply=True, db_engine=clean_db, on_changes=broken)

    assert (summary.embedded, summary.failed, summary.stopped_early) == (1, 0, False)
    assert summary.line(SPEC.model_name).startswith("indexing mode=apply model=fake-embedding")
    assert "failed=0 stopped_early=false" in summary.line(SPEC.model_name)
    assert embeddings_of(clean_db, job_id)
    assert "redis is down" in caplog.text


def test_the_indexing_package_does_not_import_rq_or_redis() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "sanket" / "indexing"
    offenders = [
        path.name
        for path in package.glob("*.py")
        if any(
            line.split()[:2] in (["import", "rq"], ["import", "redis"])
            or line.startswith(("from rq", "from redis"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]

    assert offenders == []
