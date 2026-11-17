from collections.abc import Callable, Sequence
from dataclasses import replace

import pytest
from sqlalchemy import Engine, select, update

from sanket.embeddings.client import EmbeddingError, EmbeddingSpec
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.config import (
    DimensionMismatchError,
    check_dimensions,
    column_dimensions,
)
from sanket.indexing.service import (
    MAX_CONSECUTIVE_FAILED_BATCHES,
    index_jobs,
    index_pending,
)
from sanket.models import EMBEDDING_COLUMN_DIMENSIONS, Job, JobEmbedding
from tests.factories import add_extraction
from tests.index_helpers import (
    CFG,
    SPEC,
    add_bare_job,
    add_indexable_job,
    embeddings_of,
    insert_embedding_row,
    representative_posting_id,
    search_state,
    set_description,
    set_posting_count,
)


def fake(
    fail_when: Callable[[Sequence[str]], EmbeddingError | None] | None = None,
) -> FakeEmbeddingClient:
    return FakeEmbeddingClient(
        model_name=SPEC.model_name, model_version=SPEC.model_version, fail_when=fail_when
    )


def run(engine: Engine, client: FakeEmbeddingClient, cfg=CFG, **kwargs):
    return index_pending(cfg, client, apply=True, db_engine=engine, **kwargs)


def test_first_run_writes_the_search_vector_and_the_embedding(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db, description="<p>Build APIs in Python.</p>")
    client = fake()

    summary = run(clean_db, client)

    assert (summary.scanned, summary.tsvector_updated, summary.embedded) == (1, 1, 1)
    assert (summary.unchanged, summary.failed, summary.removed) == (0, 0, 0)
    vector, search_hash = search_state(clean_db, job_id)
    assert vector is not None and "'python':" in vector
    assert search_hash
    stored = embeddings_of(clean_db, job_id)[(SPEC.model_name, SPEC.model_version)]
    assert stored == pytest.approx(client.embed_query(client.document_calls[0][0]))


def test_search_vector_weights_title_company_location_and_description(clean_db: Engine) -> None:
    job_id = add_indexable_job(
        clean_db, title="Plumber", company="Pipes", location="Oslo", description="<p>Leaks.</p>"
    )

    run(clean_db, fake())

    vector, _ = search_state(clean_db, job_id)
    assert vector is not None
    for token in ("'plumber':1A", "'pipes':2B", "'oslo':3C", "'leaks':4"):
        assert token in vector


def test_second_run_makes_no_embedding_calls_and_writes_nothing(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    add_indexable_job(clean_db, title="Data Analyst")
    run(clean_db, fake())
    client = fake()

    summary = run(clean_db, client)

    assert client.document_calls == []
    assert (summary.scanned, summary.unchanged) == (2, 2)
    assert (summary.tsvector_updated, summary.embedded, summary.failed) == (0, 0, 0)


def test_changed_description_is_embedded_again(clean_db: Engine) -> None:
    changed = add_indexable_job(clean_db, description="<p>Old text.</p>")
    untouched = add_indexable_job(clean_db, title="Data Analyst")
    run(clean_db, fake())
    before = search_state(clean_db, changed)
    set_description(clean_db, changed, "<p>Entirely new text.</p>")
    client = fake()

    summary = run(clean_db, client)

    assert summary.embedded == 1 and summary.tsvector_updated == 1 and summary.unchanged == 1
    assert len(client.document_calls) == 1 and len(client.document_calls[0]) == 1
    assert "Entirely new text." in client.document_calls[0][0]
    assert search_state(clean_db, changed) != before
    assert search_state(clean_db, untouched)[1] is not None


def test_extraction_adds_skills_and_makes_the_job_stale(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    run(clean_db, fake())
    posting_id = representative_posting_id(clean_db, job_id)
    add_extraction(clean_db, posting_id)
    client = fake()

    summary = run(clean_db, client)

    assert summary.embedded == 1
    assert "Skills: Python, PostgreSQL" in client.document_calls[0][0]
    vector, _ = search_state(clean_db, job_id)
    assert vector is not None and "'postgresql':" in vector


def test_failed_extraction_is_ignored(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    posting_id = representative_posting_id(clean_db, job_id)
    add_extraction(clean_db, posting_id, status="failed")
    client = fake()

    run(clean_db, client)

    assert "Skills" not in client.document_calls[0][0]


def test_job_without_description_or_extraction_is_indexed_from_its_fields(
    clean_db: Engine,
) -> None:
    job_id = add_bare_job(clean_db, posting_count=1)
    client = fake()

    summary = run(clean_db, client)

    assert summary.embedded == 1
    assert client.document_calls[0][0] == "Title: Engineer\nCompany: Acme"
    assert search_state(clean_db, job_id)[0] is not None


def test_text_of_excluded_sources_is_never_sent_to_the_embedding_provider(
    clean_db: Engine,
) -> None:
    excluded = add_indexable_job(clean_db, title="Plumber", source="remoteok")
    allowed = add_indexable_job(clean_db, title="Data Analyst")
    cfg = replace(CFG, excluded_sources=("remoteok",))
    client = fake()

    first = run(clean_db, client, cfg)
    second = run(clean_db, fake(), cfg)

    assert client.texts_embedded == 1 and "Data Analyst" in client.document_calls[0][0]
    assert (first.embedded, first.tsvector_updated, first.embedding_excluded) == (1, 2, 1)
    assert embeddings_of(clean_db, excluded) == {} and embeddings_of(clean_db, allowed)
    assert search_state(clean_db, excluded)[0] is not None
    assert (second.unchanged, second.embedding_excluded, second.failed) == (2, 1, 0)


def test_job_with_no_text_is_skipped(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db, title=" ", company=" ", location=None, description=None)
    client = fake()

    summary = run(clean_db, client)

    assert (summary.skipped_no_text, summary.embedded) == (1, 0)
    assert client.document_calls == []
    assert search_state(clean_db, job_id) == (None, None)


def test_new_model_version_adds_a_row_and_leaves_the_old_one(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    run(clean_db, fake())
    old = embeddings_of(clean_db, job_id)[(SPEC.model_name, "1")]
    new_spec = EmbeddingSpec(SPEC.model_name, "2", SPEC.dimensions)
    new_client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version="2")

    summary = run(clean_db, new_client, replace(CFG, spec=new_spec))

    assert summary.embedded == 1 and summary.tsvector_updated == 0
    stored = embeddings_of(clean_db, job_id)
    assert set(stored) == {(SPEC.model_name, "1"), (SPEC.model_name, "2")}
    assert stored[(SPEC.model_name, "1")] == old


def test_dead_job_loses_its_search_entry_and_all_embeddings(clean_db: Engine) -> None:
    dead = add_indexable_job(clean_db)
    alive = add_indexable_job(clean_db, title="Data Analyst")
    run(clean_db, fake())
    insert_embedding_row(clean_db, dead, "old-model-version")
    set_posting_count(clean_db, dead, 0)
    client = fake()

    summary = run(clean_db, client)

    assert summary.removed == 1 and summary.embedded == 0
    assert embeddings_of(clean_db, dead) == {}
    assert search_state(clean_db, dead) == (None, None)
    assert embeddings_of(clean_db, alive) and search_state(clean_db, alive)[0] is not None
    assert run(clean_db, fake()).removed == 0


def test_dead_job_that_was_never_indexed_is_left_alone(clean_db: Engine) -> None:
    add_indexable_job(clean_db, posting_count=0)
    client = fake()

    summary = run(clean_db, client)

    assert (summary.unchanged, summary.removed, summary.embedded) == (1, 0, 0)
    assert client.document_calls == []


def test_job_that_comes_back_to_life_is_indexed_again(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    run(clean_db, fake())
    set_posting_count(clean_db, job_id, 0)
    run(clean_db, fake())
    set_posting_count(clean_db, job_id, 2)

    summary = run(clean_db, fake())

    assert (summary.tsvector_updated, summary.embedded) == (1, 1)


def test_dry_run_counts_work_without_writing_or_calling_the_client(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)

    summary = index_pending(CFG, None, apply=False, db_engine=clean_db)

    assert (summary.tsvector_updated, summary.embedded, summary.applied) == (1, 1, False)
    assert search_state(clean_db, job_id) == (None, None)
    assert embeddings_of(clean_db, job_id) == {}


def test_applying_without_a_client_is_refused(clean_db: Engine) -> None:
    with pytest.raises(ValueError, match="client"):
        index_pending(CFG, None, apply=True, db_engine=clean_db)


def test_client_that_does_not_match_the_configured_model_is_refused(clean_db: Engine) -> None:
    other = FakeEmbeddingClient(model_name="another-model")

    with pytest.raises(ValueError, match="does not match"):
        run(clean_db, other)


def test_limit_bounds_the_work_and_the_next_run_continues_in_order(clean_db: Engine) -> None:
    ids = [add_indexable_job(clean_db, title=f"Engineer {n}") for n in range(5)]
    first_client, second_client = fake(), fake()

    first = run(clean_db, first_client, limit=2)
    second = run(clean_db, second_client, limit=10)

    assert first.embedded == 2
    assert [t.splitlines()[0] for t in first_client.document_calls[0]] == [
        "Title: Engineer 0",
        "Title: Engineer 1",
    ]
    assert (second.unchanged, second.embedded) == (2, 3)
    assert all(embeddings_of(clean_db, job_id) for job_id in ids)


def test_scanning_pages_through_more_jobs_than_one_page(clean_db: Engine) -> None:
    for n in range(7):
        add_indexable_job(clean_db, title=f"Engineer {n}")
    cfg = replace(CFG, scan_page_size=3, embedding_batch_size=2)
    client = fake()

    summary = run(clean_db, client, cfg)

    assert (summary.scanned, summary.embedded) == (7, 7)
    assert sorted(len(call) for call in client.document_calls) == [1, 1, 1, 2, 2]


def test_embeddings_are_sent_in_batches_of_the_configured_size(clean_db: Engine) -> None:
    for n in range(5):
        add_indexable_job(clean_db, title=f"Engineer {n}")
    client = fake()

    run(clean_db, client, replace(CFG, embedding_batch_size=2))

    assert [len(call) for call in client.document_calls] == [2, 2, 1]


def test_a_failed_batch_is_isolated_and_stays_pending(clean_db: Engine) -> None:
    ids = [add_indexable_job(clean_db, title=f"Engineer {n}") for n in range(4)]
    cfg = replace(CFG, embedding_batch_size=2)
    failing = fake(
        fail_when=lambda texts: (
            EmbeddingError("quota") if any("Engineer 0" in t for t in texts) else None
        )
    )

    summary = run(clean_db, failing, cfg)

    assert (summary.embedded, summary.failed) == (2, 2)
    assert not summary.stopped_early
    assert [bool(embeddings_of(clean_db, i)) for i in ids] == [False, False, True, True]
    assert all(search_state(clean_db, i)[0] is not None for i in ids)
    healthy = fake()
    retry = run(clean_db, healthy, cfg)
    assert (retry.embedded, retry.unchanged, retry.failed) == (2, 2, 0)
    assert healthy.texts_embedded == 2


def test_rejected_input_is_isolated_to_the_offending_job(clean_db: Engine) -> None:
    ids = [add_indexable_job(clean_db, title=f"Engineer {n}") for n in range(3)]
    client = fake(
        fail_when=lambda texts: (
            EmbeddingError("invalid input", retryable=False)
            if any("Engineer 1" in t for t in texts)
            else None
        )
    )

    summary = run(clean_db, client)

    assert (summary.embedded, summary.failed) == (2, 1)
    assert [bool(embeddings_of(clean_db, i)) for i in ids] == [True, False, True]


def test_run_stops_after_consecutive_failed_batches(clean_db: Engine) -> None:
    for n in range(10):
        add_indexable_job(clean_db, title=f"Engineer {n}")
    client = fake(fail_when=lambda texts: EmbeddingError("quota exceeded"))

    summary = run(clean_db, client, replace(CFG, embedding_batch_size=2))

    assert summary.stopped_early
    assert len(client.document_calls) == MAX_CONSECUTIVE_FAILED_BATCHES
    assert summary.failed == 2 * MAX_CONSECUTIVE_FAILED_BATCHES
    assert summary.embedded == 0


def test_a_successful_batch_resets_the_failure_streak(clean_db: Engine) -> None:
    for n in range(8):
        add_indexable_job(clean_db, title=f"Engineer {n}")
    seen = iter(range(100))

    def fail_every_other_batch(texts: object) -> EmbeddingError | None:
        return EmbeddingError("flaky") if next(seen) % 2 == 0 else None

    client = fake(fail_when=fail_every_other_batch)

    summary = run(clean_db, client, replace(CFG, embedding_batch_size=1))

    assert not summary.stopped_early
    assert (summary.embedded, summary.failed) == (4, 4)


def test_embedding_of_a_job_that_died_during_the_call_is_not_stored(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)

    def kill_job_during_call(texts: object) -> None:
        set_posting_count(clean_db, job_id, 0)

    client = fake(fail_when=kill_job_during_call)

    summary = run(clean_db, client)

    assert summary.embedded == 1  # counted as handled, but nothing was stored
    assert embeddings_of(clean_db, job_id) == {}


def test_index_jobs_touches_only_the_given_jobs(clean_db: Engine) -> None:
    wanted = add_indexable_job(clean_db)
    other = add_indexable_job(clean_db, title="Data Analyst")
    client = fake()

    summary = index_jobs([wanted, 99999, wanted], CFG, client, clean_db)

    assert (summary.scanned, summary.embedded) == (1, 1)
    assert embeddings_of(clean_db, wanted) and embeddings_of(clean_db, other) == {}
    again = fake()
    assert index_jobs([wanted], CFG, again, clean_db).unchanged == 1
    assert again.document_calls == []


def test_index_jobs_removes_a_dead_job(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    index_jobs([job_id], CFG, fake(), clean_db)
    set_posting_count(clean_db, job_id, 0)

    summary = index_jobs([job_id], CFG, fake(), clean_db)

    assert summary.removed == 1
    assert embeddings_of(clean_db, job_id) == {}


def test_search_vector_is_cleared_hash_and_all_by_removal(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    run(clean_db, fake())
    with clean_db.begin() as conn:
        conn.execute(update(Job).where(Job.id == job_id).values(posting_count=0))

    run(clean_db, fake())

    with clean_db.connect() as conn:
        row = conn.execute(select(Job.search_vector, Job.search_hash)).one()
        assert (row[0], row[1]) == (None, None)
        assert conn.execute(select(JobEmbedding.id)).all() == []


# --- dimension check ---------------------------------------------------------------------


def test_database_column_width_is_read_from_the_catalog(db_engine: Engine) -> None:
    assert column_dimensions(db_engine) == EMBEDDING_COLUMN_DIMENSIONS
    check_dimensions(EMBEDDING_COLUMN_DIMENSIONS, db_engine)


def test_setting_that_differs_from_the_column_fails_fast_before_any_work(
    clean_db: Engine,
) -> None:
    add_indexable_job(clean_db)
    cfg = replace(CFG, spec=EmbeddingSpec(SPEC.model_name, "1", 1024))
    client = FakeEmbeddingClient(dimensions=1024, model_name=SPEC.model_name)

    with pytest.raises(DimensionMismatchError, match="1024"):
        index_pending(cfg, client, apply=True, db_engine=clean_db)

    assert client.document_calls == []
    with pytest.raises(DimensionMismatchError):
        check_dimensions(1024, clean_db)


class NarrowClient(FakeEmbeddingClient):
    """Returns vectors one dimension short, like a misconfigured provider."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector[:-1] for vector in super().embed_documents(texts)]


def test_client_returning_the_wrong_width_is_a_failure_not_a_crash(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    client = NarrowClient(model_name=SPEC.model_name, model_version=SPEC.model_version)

    summary = index_pending(CFG, client, apply=True, db_engine=clean_db)

    assert (summary.embedded, summary.failed) == (0, 1)
    assert embeddings_of(clean_db, job_id) == {}
