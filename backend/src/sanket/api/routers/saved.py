"""Saved jobs: the caller's bookmarks, kept on the server. Every route acts for the owner given
by `get_header_owner_id` (a stream token never opens these)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from sanket import saved_jobs
from sanket.api.deps import ApiContext, get_context, get_header_owner_id
from sanket.api.job_schemas import SavedJobList, SavedJobOut, saved_out
from sanket.search.details import load_details

router = APIRouter(prefix="/saved-jobs", tags=["saved jobs"])

Context = Annotated[ApiContext, Depends(get_context)]
Owner = Annotated[str, Depends(get_header_owner_id)]


@router.get("", response_model=SavedJobList, summary="List your saved jobs")
def list_saved(context: Context, owner: Owner) -> SavedJobList:
    bookmarks = saved_jobs.list_saved(owner, context.db_engine)
    details = load_details([mark.job_id for mark in bookmarks], context.db_engine)
    return SavedJobList(
        items=[saved_out(m.job_id, m.saved_at, details.get(m.job_id)) for m in bookmarks]
    )


@router.put(
    "/{job_id}",
    response_model=SavedJobOut,
    summary="Save a job",
    description="Idempotent: saving a saved job keeps its first `saved_at`.",
)
def save_job(job_id: int, context: Context, owner: Owner) -> SavedJobOut:
    mark = saved_jobs.save(owner, job_id, context.db_engine)
    if mark is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    details = load_details([job_id], context.db_engine).get(job_id)
    return saved_out(mark.job_id, mark.saved_at, details)


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a saved job",
    description="Idempotent: removing a job that is not saved also answers 204.",
)
def unsave_job(job_id: int, context: Context, owner: Owner) -> Response:
    saved_jobs.unsave(owner, job_id, context.db_engine)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
