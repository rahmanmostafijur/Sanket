"""Helpers that seed jobs for the indexing tests and read what indexing stored."""

from sqlalchemy import Engine, insert, select, update

from sanket.embeddings.client import EmbeddingSpec
from sanket.indexing.config import IndexConfig
from sanket.models import Job, JobEmbedding, Posting
from tests.factories import add_extraction, add_posting
from tests.test_job_schema import add_job

SPEC = EmbeddingSpec(model_name="fake-embedding", model_version="1", dimensions=768)
CFG = IndexConfig(spec=SPEC, max_description_chars=2000, embedding_batch_size=10, batch_limit=100)

_fingerprints = iter(range(1, 10_000))


def add_indexable_job(
    engine: Engine,
    *,
    title: str = "Backend Engineer",
    company: str = "Acme",
    location: str | None = "Berlin",
    description: str | None = "<p>Build APIs.</p>",
    with_extraction: bool = False,
    posting_count: int = 1,
    source: str = "greenhouse",
    fingerprint: str | None = None,
) -> int:
    """A job with one representative posting (and optionally an ok extraction)."""
    posting_id = add_posting(
        engine,
        source=source,
        title=title,
        company=company,
        location=location,
        description=description,
    )
    job_id = add_job(
        engine,
        fingerprint=fingerprint or f"fp1:test-{next(_fingerprints)}",
        representative_posting_id=posting_id,
        posting_count=posting_count,
    )
    with engine.begin() as conn:
        conn.execute(update(Job).where(Job.id == job_id).values(title=title, company=company))
        conn.execute(update(Job).where(Job.id == job_id).values(location=location))
        conn.execute(update(Posting).where(Posting.id == posting_id).values(job_id=job_id))
    if with_extraction:
        add_extraction(engine, posting_id)
    return job_id


def add_bare_job(engine: Engine, **values: object) -> int:
    """A job with no representative posting."""
    return add_job(engine, fingerprint=f"fp1:bare-{next(_fingerprints)}", **values)


def set_description(engine: Engine, job_id: int, description: str) -> None:
    with engine.begin() as conn:
        posting_id = conn.execute(
            select(Job.representative_posting_id).where(Job.id == job_id)
        ).scalar_one()
        conn.execute(
            update(Posting).where(Posting.id == posting_id).values(description=description)
        )


def set_posting_count(engine: Engine, job_id: int, count: int) -> None:
    with engine.begin() as conn:
        conn.execute(update(Job).where(Job.id == job_id).values(posting_count=count))


def embeddings_of(engine: Engine, job_id: int) -> dict[tuple[str, str], list[float]]:
    stmt = select(
        JobEmbedding.model_name, JobEmbedding.model_version, JobEmbedding.embedding
    ).where(JobEmbedding.job_id == job_id)
    with engine.connect() as conn:
        return {(row[0], row[1]): list(row[2]) for row in conn.execute(stmt)}


def search_state(engine: Engine, job_id: int) -> tuple[str | None, str | None]:
    """The stored `(search_vector as text, search_hash)` of a job."""
    stmt = select(Job.search_vector, Job.search_hash)
    with engine.connect() as conn:
        row = conn.execute(stmt.where(Job.id == job_id)).one()
    return (None if row[0] is None else str(row[0]), row[1])


def insert_embedding_row(engine: Engine, job_id: int, model_version: str) -> None:
    stmt = insert(JobEmbedding).values(
        job_id=job_id,
        model_name=SPEC.model_name,
        model_version=model_version,
        dimension=SPEC.dimensions,
        content_hash="old",
        embedding=[0.5] * SPEC.dimensions,
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def representative_posting_id(engine: Engine, job_id: int) -> int:
    with engine.connect() as conn:
        posting_id = conn.execute(
            select(Job.representative_posting_id).where(Job.id == job_id)
        ).scalar_one()
    assert posting_id is not None
    return posting_id
