"""`GET /jobs` (browse without a query) and `GET /jobs/{job_id}` (one job in full).

Both are as open as search: public with SEARCH_PUBLIC, otherwise they need a credential.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from sanket.api.deps import ApiContext, get_context, require_search_access
from sanket.api.job_schemas import JobDetailOut, JobListParams, JobListResponse, detail_out
from sanket.api.schemas import job_from_details
from sanket.search.browse import list_jobs, load_job

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_search_access)])

Context = Annotated[ApiContext, Depends(get_context)]


@router.get(
    "",
    response_model=JobListResponse,
    summary="List jobs",
    description="Live jobs by posting date, with the same filters as search. Show "
    "`attribution` and link to `url` with every job.",
)
def browse_jobs(params: Annotated[JobListParams, Query()], context: Context) -> JobListResponse:
    page = list_jobs(
        params.to_filters(),
        params.sort,
        limit=params.limit,
        offset=params.offset,
        db_engine=context.db_engine,
    )
    return JobListResponse(
        limit=params.limit,
        offset=params.offset,
        total=page.total,
        has_more=params.offset + len(page.jobs) < page.total,
        items=[job_from_details(details) for details in page.jobs],
    )


@router.get(
    "/{job_id}",
    response_model=JobDetailOut,
    summary="Get a job",
    description="One live job with its description and every listing of it (404 when the "
    "job does not exist or is no longer listed).",
)
def get_job(job_id: int, context: Context) -> JobDetailOut:
    view = load_job(job_id, context.db_engine)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return detail_out(view)
