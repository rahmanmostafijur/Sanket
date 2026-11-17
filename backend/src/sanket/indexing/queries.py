"""Low-level retrieval primitives over the index: full-text and vector candidates.

Each function returns candidates best first, with a 1-based `rank` to fuse on (rank, not
score, is what the hybrid search combines) and the raw `score` for inspection. Both queries
are written so the planner can use the index: `@@` against the GIN index for text, and
`ORDER BY embedding <=> :q LIMIT n` against the HNSW index for vectors.

Both accept optional `SearchFilters` (`sanket.indexing.filters`). They are applied inside the
query, so the candidates are the best matches among the jobs that pass, not the passing
subset of the best matches. Without filters the statements are the plain Phase 4 shapes.

All user input reaches the database as bound parameters only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Engine, Select, Text, bindparam, func, literal_column, select

from sanket.config import settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingSpec
from sanket.indexing.document import TEXT_SEARCH_CONFIG
from sanket.indexing.filters import SearchFilters, join_job, restrict_to_live_jobs
from sanket.models import EMBEDDING_COLUMN_DIMENSIONS, Job, JobEmbedding

# pgvector refuses an ef_search above this.
MAX_EF_SEARCH = 1000
# With a WHERE on the model (rows of several models coexist during a migration), the index
# scan keeps going until enough matching rows are found instead of returning too few.
# Needs pgvector 0.8 or newer (Neon and the local image have it).
ITERATIVE_SCAN_MODE = "relaxed_order"


@dataclass(frozen=True)
class Candidate:
    job_id: int
    rank: int
    # ts_rank_cd for text (higher is better); cosine distance for vectors (lower is better).
    score: float


def websearch_query(text: str) -> ColumnElement[object]:
    """`websearch_to_tsquery('simple', :text)`.

    That function accepts any string and never raises: quoted phrases, `or` and a leading
    `-` are understood, everything else is plain terms. The text is a bound parameter.
    """
    config: ColumnElement[Any] = literal_column(f"'{TEXT_SEARCH_CONFIG}'::regconfig")
    return func.websearch_to_tsquery(config, bindparam("query_text", text, type_=Text))


def fulltext_statement(
    query: str, limit: int, filters: SearchFilters | None = None
) -> Select[int, float]:
    tsquery = websearch_query(query)
    score = func.ts_rank_cd(Job.search_vector, tsquery)
    stmt = (
        select(Job.id, score.label("score"))
        .where(Job.search_vector.bool_op("@@")(tsquery))
        .order_by(score.desc(), Job.id)
        .limit(limit)
    )
    return restrict_to_live_jobs(stmt, filters or SearchFilters())


def fulltext_candidates(
    query: str, limit: int, db_engine: Engine = engine, *, filters: SearchFilters | None = None
) -> list[Candidate]:
    """Jobs whose search vector matches `query`, best `ts_rank_cd` first (ties by id).

    Title matches outrank description matches through the A to D weights. A query with no
    searchable terms returns nothing. Jobs without postings never match.
    """
    if limit < 1 or not query.strip():
        return []
    with db_engine.connect() as conn:
        rows = conn.execute(fulltext_statement(query, limit, filters)).all()
    return [Candidate(job_id, rank, float(score)) for rank, (job_id, score) in enumerate(rows, 1)]


def vector_statement(
    embedding: Sequence[float],
    limit: int,
    spec: EmbeddingSpec | None = None,
    filters: SearchFilters | None = None,
) -> Select[int, float]:
    """Nearest rows by cosine distance, restricted to one model when `spec` is given.

    The model filter is needed whenever more than one model is stored. Without it, and
    without `filters`, the statement is the plain nearest-neighbour shape the HNSW index is
    built for. With `filters` (even an empty one) the rows are joined to their job, which
    must have postings and pass the filters; the iterative scan setting then keeps the index
    scan going until `limit` rows pass.
    """
    distance = JobEmbedding.embedding.cosine_distance(list(embedding))
    stmt = select(JobEmbedding.job_id, distance.label("distance"))
    if spec is not None:
        stmt = stmt.where(
            JobEmbedding.model_name == spec.model_name,
            JobEmbedding.model_version == spec.model_version,
        )
    stmt = stmt.order_by(distance, JobEmbedding.job_id).limit(limit)
    if filters is not None:
        stmt = restrict_to_live_jobs(join_job(stmt), filters)
    return stmt


def vector_candidates(
    embedding: Sequence[float],
    spec: EmbeddingSpec,
    limit: int,
    ef_search: int | None = None,
    db_engine: Engine = engine,
    *,
    filters: SearchFilters | None = None,
) -> list[Candidate]:
    """The jobs nearest to `embedding` (cosine distance) among the vectors of `spec`.

    `hnsw.ef_search` (default HNSW_EF_SEARCH) is the number of candidates the index examines:
    higher is more accurate and slower. It is raised to `limit` when lower, because the index
    cannot return more rows than it examines, and capped at the pgvector maximum. It is set
    with `set_config(..., true)`, which lasts for this transaction only (like SET LOCAL, but
    accepts bound parameters). With `filters`, the filters are part of the query (see
    `vector_statement`). The iterative scan may return rows slightly out of distance order,
    so the rows are put in exact order here before they are ranked.
    """
    if len(embedding) != EMBEDDING_COLUMN_DIMENSIONS:
        raise ValueError(
            f"query vector has {len(embedding)} dimensions, expected {EMBEDDING_COLUMN_DIMENSIONS}"
        )
    if limit < 1:
        return []
    effective = min(max(ef_search or settings.hnsw_ef_search, limit), MAX_EF_SEARCH)
    with db_engine.begin() as conn:
        conn.execute(select(func.set_config("hnsw.ef_search", str(effective), True)))
        conn.execute(select(func.set_config("hnsw.iterative_scan", ITERATIVE_SCAN_MODE, True)))
        rows = conn.execute(vector_statement(embedding, limit, spec, filters)).all()
    ordered = sorted(((float(dist), job_id) for job_id, dist in rows))
    return [Candidate(job_id, rank, dist) for rank, (dist, job_id) in enumerate(ordered, 1)]
