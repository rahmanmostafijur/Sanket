"""Request and response models of the job list, job detail and saved-job endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from sanket.api.schemas import DEFAULT_LIMIT, MAX_LIMIT, FilterParams, JobOut, job_fields
from sanket.search.attribution import source_info
from sanket.search.browse import BrowseSort, JobView, PostingRef
from sanket.search.details import JobDetails

# Browsing is not capped by a candidate list, but an offset this deep is never a person paging.
MAX_BROWSE_OFFSET = 10_000


class JobListParams(FilterParams):
    """Query parameters of `GET /jobs`."""

    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size.")
    offset: int = Field(0, ge=0, le=MAX_BROWSE_OFFSET, description="Jobs to skip.")
    sort: BrowseSort = Field(BrowseSort.NEWEST, description="By posting date.")


class JobListResponse(BaseModel):
    limit: int
    offset: int
    total: int = Field(description="Live jobs that pass the filters.")
    has_more: bool
    items: list[JobOut]


class PostingOut(BaseModel):
    source: str
    name: str = Field(description="Display name of the source.")
    url: str | None = Field(description="The original listing. Always link to it.")
    attribution: str | None = Field(description="Credit line the source asks to be shown.")
    published_at: datetime | None


class JobDetailOut(JobOut):
    description: str | None = Field(
        description="The representative posting's description as plain text (never HTML)."
    )
    postings: list[PostingOut] = Field(description="Every listing of this job, newest first.")


class SavedJobOut(BaseModel):
    job_id: int
    saved_at: datetime
    job: JobOut | None = Field(description="Null when the job is no longer listed.")


class SavedJobList(BaseModel):
    items: list[SavedJobOut]


def posting_out(ref: PostingRef) -> PostingOut:
    info = source_info(ref.source)
    return PostingOut(
        source=ref.source,
        name=info.name,
        url=ref.url,
        attribution=info.attribution,
        published_at=ref.published_at,
    )


def detail_out(view: JobView) -> JobDetailOut:
    return JobDetailOut(
        **job_fields(view.details),
        description=view.description,
        postings=[posting_out(ref) for ref in view.postings],
    )


def saved_out(job_id: int, saved_at: datetime, details: JobDetails | None) -> SavedJobOut:
    job = JobOut(**job_fields(details)) if details is not None else None
    return SavedJobOut(job_id=job_id, saved_at=saved_at, job=job)
