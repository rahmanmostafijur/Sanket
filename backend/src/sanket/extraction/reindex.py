"""Index the jobs whose representative posting has just been extracted.

The job filters (work mode, seniority, employment type, skills) read the newest ok extraction
of a job's representative posting at query time (`sanket.indexing.filters`), so a new
extraction counts in filtered results at once. The job's full-text vector and embedding are
built from that extraction too, and those only change when the job is indexed again. This runs
the indexing service for exactly those jobs (hash gated, so an unchanged document costs
nothing) with the same matching observer as an indexing run.

Nothing here fails an extraction: errors are logged, and the jobs stay pending for the next
`python -m sanket.indexing --apply`, which finds every job whose document changed.
"""

import logging
from collections.abc import Callable, Sequence

from sqlalchemy import Engine, select

from sanket.config import Settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient
from sanket.embeddings.gemini import GeminiEmbeddingClient
from sanket.indexing.config import IndexConfig, config_from_settings
from sanket.indexing.service import IndexObserver, IndexSummary, index_jobs
from sanket.matching.triggers import index_observer_from_settings
from sanket.models import Job

logger = logging.getLogger(__name__)

Reindexer = Callable[[Sequence[int]], None]


def represented_jobs(posting_ids: Sequence[int], db_engine: Engine = engine) -> list[int]:
    """Ids of the jobs whose representative posting is one of `posting_ids`."""
    stmt = (
        select(Job.id)
        .where(Job.representative_posting_id.in_(list(posting_ids)))
        .order_by(Job.id)
    )
    with db_engine.connect() as conn:
        return list(conn.scalars(stmt))


def reindex_postings(
    posting_ids: Sequence[int],
    cfg: IndexConfig,
    client: EmbeddingClient,
    observer: IndexObserver | None = None,
    db_engine: Engine = engine,
) -> IndexSummary | None:
    """Index the jobs these postings represent; None when they represent none."""
    job_ids = represented_jobs(posting_ids, db_engine) if posting_ids else []
    if not job_ids:
        return None
    summary = index_jobs(job_ids, cfg, client, db_engine, on_changes=observer)
    logger.info("reindex after extraction %s", summary.line(cfg.spec.model_name))
    return summary


def reindexer_from_settings(
    config: Settings,
    db_engine: Engine = engine,
    embedder: EmbeddingClient | None = None,
) -> Reindexer | None:
    """The hook to call with extracted posting ids, or None when it is turned off
    (INDEX_AFTER_EXTRACTION) or there is no embedding key."""
    if not config.index_after_extraction:
        return None
    cfg = config_from_settings(config)
    client = embedder
    if client is None and config.gemini_api_key is not None:
        client = GeminiEmbeddingClient(
            config.gemini_api_key,
            cfg.spec.model_name,
            cfg.spec.dimensions,
            model_version=cfg.spec.model_version,
            requests_per_minute=config.embedding_requests_per_minute,
        )
    if client is None:
        logger.info("GEMINI_API_KEY is not set: jobs are not indexed after extraction")
        return None
    observer = index_observer_from_settings(config)
    embedding_client = client

    def reindex(posting_ids: Sequence[int]) -> None:
        try:
            reindex_postings(posting_ids, cfg, embedding_client, observer, db_engine)
        except Exception:  # indexing must never fail the extraction that triggered it
            logger.exception(
                "Indexing after extraction failed; `python -m sanket.indexing --apply` "
                "picks the jobs up"
            )

    return reindex
