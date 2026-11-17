"""The search service: retrieve, page the fused list and load details for the page.

Paging works on the fused list, which holds at most `SEARCH_CANDIDATES` jobs. An offset at or
past its end returns an empty page, so deep paging beyond the cap yields nothing; `has_more`
says whether more results exist below the page that was returned.
"""

from dataclasses import dataclass

from sqlalchemy import Engine

from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient
from sanket.indexing.filters import SearchFilters
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.details import JobDetails, load_details
from sanket.search.retrieval import SearchConfig, SearchMode, matched_by, retrieve


@dataclass(frozen=True)
class SearchHit:
    details: JobDetails
    score: float
    matched_by: str


@dataclass(frozen=True)
class SearchPage:
    query: str
    limit: int
    offset: int
    hits: list[SearchHit]
    total_candidates: int
    has_more: bool
    degraded: bool
    degraded_reason: str | None


def search(
    query: str,
    filters: SearchFilters,
    cfg: SearchConfig,
    client: EmbeddingClient | None,
    *,
    limit: int,
    offset: int,
    mode: SearchMode = SearchMode.HYBRID,
    cache: QueryEmbeddingCache | None = None,
    db_engine: Engine = engine,
) -> SearchPage:
    retrieval = retrieve(query, filters, cfg, client, mode=mode, cache=cache, db_engine=db_engine)
    total = len(retrieval.items)
    page = retrieval.items[offset : offset + limit]
    details = load_details([item.job_id for item in page], db_engine)
    # A job deleted between retrieval and loading its details is left out of the page.
    hits = [
        SearchHit(details[item.job_id], item.score, matched_by(item))
        for item in page
        if item.job_id in details
    ]
    return SearchPage(
        query=query,
        limit=limit,
        offset=offset,
        hits=hits,
        total_candidates=total,
        has_more=offset + limit < total,
        degraded=retrieval.degraded,
        degraded_reason=retrieval.degraded_reason,
    )
