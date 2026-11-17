"""Candidate retrieval and fusion: the part of search shared by the API and the evaluation.

`retrieve` runs the full-text and the vector query (each limited to `candidates` and
pre-filtered), fuses their ranks with RRF and returns the fused list best first. If the query
embedding cannot be obtained, it answers from full text only and says so (`degraded`), rather
than failing the request.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine

from sanket.config import Settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient, EmbeddingError, EmbeddingSpec
from sanket.indexing.filters import SearchFilters
from sanket.indexing.queries import fulltext_candidates, vector_candidates
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.fusion import FusedItem, rrf_fuse

REASON_EMBEDDINGS_DISABLED = "embeddings_disabled"
REASON_EMBEDDING_FAILED = "embedding_failed"
# Positions of the two ranked lists inside a fused item.
TEXT_LIST = 0
VECTOR_LIST = 1

logger = logging.getLogger(__name__)


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    TEXT = "text"
    VECTOR = "vector"


@dataclass(frozen=True)
class SearchConfig:
    spec: EmbeddingSpec
    candidates: int
    rrf_k: int
    fulltext_weight: float
    vector_weight: float
    ef_search: int | None = None


def search_config_from_settings(config: Settings) -> SearchConfig:
    return SearchConfig(
        spec=EmbeddingSpec(
            model_name=config.embedding_model,
            model_version=config.embedding_model_version,
            dimensions=config.embedding_dimensions,
        ),
        candidates=config.search_candidates,
        rrf_k=config.search_rrf_k,
        fulltext_weight=config.search_fulltext_weight,
        vector_weight=config.search_vector_weight,
        ef_search=config.hnsw_ef_search,
    )


@dataclass(frozen=True)
class Retrieval:
    """The fused candidates (at most `candidates`), best first, and how they were obtained."""

    items: list[FusedItem]
    degraded: bool = False
    degraded_reason: str | None = None


def matched_by(item: FusedItem) -> str:
    """Which lists the job appeared in: `text`, `vector` or `both`."""
    in_text = item.ranks[TEXT_LIST] is not None
    in_vector = item.ranks[VECTOR_LIST] is not None
    if in_text and in_vector:
        return "both"
    return "text" if in_text else "vector"


def _wanted_lists(mode: SearchMode, cfg: SearchConfig) -> tuple[bool, bool]:
    """Whether to run the text query and the vector query. A weight of 0 switches a list off."""
    if mode is SearchMode.TEXT:
        return True, False
    if mode is SearchMode.VECTOR:
        return False, True
    return cfg.fulltext_weight > 0, cfg.vector_weight > 0


def _query_vector(
    query: str,
    spec: EmbeddingSpec,
    client: EmbeddingClient | None,
    cache: QueryEmbeddingCache | None,
) -> tuple[list[float] | None, str | None]:
    """The query embedding, or `(None, reason)` when it cannot be had. Never raises."""
    if client is None:
        return None, REASON_EMBEDDINGS_DISABLED
    text = " ".join(query.split())
    try:
        if cache is None:
            return client.embed_query(text), None
        return cache.get_or_embed(spec, text, client.embed_query), None
    except EmbeddingError as error:
        logger.warning("Query embedding failed, answering from full text only: %s", error)
    except Exception:  # a provider fault must degrade the search, not fail it
        logger.exception("Unexpected query embedding failure, answering from full text only")
    return None, REASON_EMBEDDING_FAILED


def retrieve(
    query: str,
    filters: SearchFilters,
    cfg: SearchConfig,
    client: EmbeddingClient | None,
    *,
    mode: SearchMode = SearchMode.HYBRID,
    cache: QueryEmbeddingCache | None = None,
    db_engine: Engine = engine,
) -> Retrieval:
    want_text, want_vector = _wanted_lists(mode, cfg)
    text_ids: list[int] = []
    vector_ids: list[int] = []
    reason: str | None = None

    if want_text:
        found = fulltext_candidates(query, cfg.candidates, db_engine, filters=filters)
        text_ids = [candidate.job_id for candidate in found]
    if want_vector:
        vector, reason = _query_vector(query, cfg.spec, client, cache)
        if vector is not None:
            found = vector_candidates(
                vector,
                cfg.spec,
                cfg.candidates,
                cfg.ef_search,
                db_engine,
                filters=filters,
            )
            vector_ids = [candidate.job_id for candidate in found]

    # With a single list requested the weights are irrelevant; keep them at 1 so a weight of 0
    # (which only switches a list off in hybrid mode) cannot empty a text-only or vector-only run.
    single = mode is not SearchMode.HYBRID
    weights = [1.0, 1.0] if single else [cfg.fulltext_weight, cfg.vector_weight]
    fused = rrf_fuse([text_ids, vector_ids], cfg.rrf_k, weights)[: cfg.candidates]
    return Retrieval(fused, degraded=reason is not None, degraded_reason=reason)
