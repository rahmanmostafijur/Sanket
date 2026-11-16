"""Database access for the indexing worker: read job inputs, write index entries."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    Select,
    Text,
    and_,
    bindparam,
    delete,
    exists,
    func,
    literal_column,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from sanket.embeddings.client import EmbeddingSpec
from sanket.extraction.runner import STATUS_OK
from sanket.indexing.document import TEXT_SEARCH_CONFIG, WeightedText
from sanket.models import Job, JobEmbedding, Posting, PostingExtraction

# The excerpt is cut after HTML removal, but the database cuts the raw text first so a huge
# description is not transferred just to be thrown away. Tags make up part of an HTML
# description, so the raw cut is a multiple of the excerpt length.
DESCRIPTION_FETCH_FACTOR = 4

REGCONFIG = f"'{TEXT_SEARCH_CONFIG}'::regconfig"
WEIGHTS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class JobSource:
    """Everything the indexer reads about one job, and what is stored for it already."""

    job_id: int
    title: str
    company: str
    location: str | None
    posting_count: int
    description: str | None
    extraction: dict[str, Any] | None
    search_hash: str | None
    has_search_vector: bool
    embedding_hash: str | None
    has_any_embedding: bool


@dataclass(frozen=True)
class SearchWrite:
    job_id: int
    weighted: WeightedText
    search_hash: str


@dataclass(frozen=True)
class EmbeddingWrite:
    job_id: int
    content_hash: str
    embedding: list[float]


def _latest_extraction(posting: Any) -> Any:
    """The data of the newest successful extraction of a posting, as a scalar subquery."""
    return (
        select(PostingExtraction.data)
        .where(PostingExtraction.posting_id == posting.id, PostingExtraction.status == STATUS_OK)
        .order_by(PostingExtraction.schema_version.desc(), PostingExtraction.prompt_version.desc())
        .limit(1)
        .scalar_subquery()
    )


def _source_query(spec: EmbeddingSpec, description_chars: int) -> Select[Any]:
    posting = aliased(Posting)
    embedding = aliased(JobEmbedding)
    return (
        select(
            Job.id.label("job_id"),
            Job.title,
            Job.company,
            Job.location,
            Job.posting_count,
            func.left(posting.description, description_chars * DESCRIPTION_FETCH_FACTOR).label(
                "description"
            ),
            _latest_extraction(posting).label("extraction"),
            Job.search_hash,
            Job.search_vector.is_not(None).label("has_search_vector"),
            embedding.content_hash.label("embedding_hash"),
            exists().where(JobEmbedding.job_id == Job.id).label("has_any_embedding"),
        )
        .select_from(Job)
        .outerjoin(posting, posting.id == Job.representative_posting_id)
        .outerjoin(
            embedding,
            and_(
                embedding.job_id == Job.id,
                embedding.model_name == spec.model_name,
                embedding.model_version == spec.model_version,
            ),
        )
        .order_by(Job.id)
    )


def load_job_sources(
    conn: Connection,
    spec: EmbeddingSpec,
    description_chars: int,
    *,
    after_id: int | None = None,
    job_ids: Sequence[int] | None = None,
    limit: int | None = None,
) -> list[JobSource]:
    """Jobs in id order: after a cursor (keyset pagination), or exactly these ids."""
    stmt = _source_query(spec, description_chars)
    if after_id is not None:
        stmt = stmt.where(Job.id > after_id)
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(job_ids))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [JobSource(**row._mapping) for row in conn.execute(stmt)]


def _weighted_tsvector() -> ColumnElement[Any]:
    """`setweight(to_tsvector(cfg, :a), 'A') || ... || setweight(..., 'D')`, bound by name."""
    config: ColumnElement[Any] = literal_column(REGCONFIG)
    parts: list[ColumnElement[Any]] = [
        func.setweight(
            func.to_tsvector(config, bindparam(f"text_{weight.lower()}", type_=Text)),
            literal_column(f"'{weight}'"),
        )
        for weight in WEIGHTS
    ]
    return reduce(lambda left, right: left.op("||")(right), parts)


def write_search_vectors(conn: Connection, writes: Sequence[SearchWrite]) -> None:
    """Store the weighted tsvector and its hash; `updated_at` is for canonical changes only."""
    if not writes:
        return
    stmt = (
        update(Job)
        .where(Job.id == bindparam("target_job_id"))
        .values(search_vector=_weighted_tsvector(), search_hash=bindparam("new_hash"))
    )
    params = [
        {
            "target_job_id": write.job_id,
            "new_hash": write.search_hash,
            "text_a": write.weighted.a,
            "text_b": write.weighted.b,
            "text_c": write.weighted.c,
            "text_d": write.weighted.d,
        }
        for write in writes
    ]
    conn.execute(stmt, params)


def write_embeddings(
    conn: Connection, spec: EmbeddingSpec, writes: Sequence[EmbeddingWrite]
) -> int:
    """Upsert embeddings for the active model and return how many were written.

    Jobs that vanished or lost their last posting since they were read are left out.
    """
    if not writes:
        return 0
    alive = set(
        conn.scalars(
            select(Job.id).where(
                Job.id.in_([write.job_id for write in writes]), Job.posting_count > 0
            )
        )
    )
    rows = [
        {
            "job_id": write.job_id,
            "model_name": spec.model_name,
            "model_version": spec.model_version,
            "dimension": spec.dimensions,
            "content_hash": write.content_hash,
            "embedding": write.embedding,
        }
        for write in writes
        if write.job_id in alive
    ]
    if not rows:
        return 0
    stmt = insert(JobEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[JobEmbedding.job_id, JobEmbedding.model_name, JobEmbedding.model_version],
        set_={
            "dimension": stmt.excluded.dimension,
            "content_hash": stmt.excluded.content_hash,
            "embedding": stmt.excluded.embedding,
            "updated_at": func.now(),
        },
    )
    conn.execute(stmt)
    return len(rows)


def remove_index_entries(conn: Connection, job_ids: Sequence[int]) -> None:
    """Drop the search vector and every model's embedding of jobs that have no postings."""
    if not job_ids:
        return
    dead = select(Job.id).where(Job.id.in_(job_ids), Job.posting_count == 0)
    conn.execute(delete(JobEmbedding).where(JobEmbedding.job_id.in_(dead)))
    conn.execute(
        update(Job)
        .where(Job.id.in_(job_ids), Job.posting_count == 0)
        .values(search_vector=None, search_hash=None)
    )
