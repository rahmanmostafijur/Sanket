"""`GET /search`: hybrid (full-text plus vector) job search."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sanket.api.deps import ApiContext, get_context
from sanket.api.schemas import SearchParams, SearchResponse, response_from_page
from sanket.search.service import search

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search jobs",
    description=(
        "Hybrid search: full-text and vector candidates (each pre-filtered) are fused by "
        "reciprocal rank. If the query cannot be embedded, results come from full text only "
        "and `degraded` is true. Show `attribution` and link to `url` with every result."
    ),
)
def search_jobs(
    params: Annotated[SearchParams, Query()],
    context: Annotated[ApiContext, Depends(get_context)],
) -> SearchResponse:
    page = search(
        params.q,
        params.to_filters(),
        context.search_config,
        context.embedding_client,
        limit=params.limit,
        offset=params.offset,
        cache=context.query_cache,
        db_engine=context.db_engine,
    )
    return response_from_page(page)
