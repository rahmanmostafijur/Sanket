"""Saved jobs: an owner's bookmarks. Every function takes the owner and filters by it, so one
owner never sees or changes another's bookmarks."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, Text, delete, literal, select
from sqlalchemy.dialects.postgresql import insert

from sanket.db import engine
from sanket.models import Job, SavedJob

MAX_SAVED_LISTED = 500


@dataclass(frozen=True)
class Bookmark:
    job_id: int
    saved_at: datetime


def list_saved(owner_id: str, db_engine: Engine = engine) -> list[Bookmark]:
    """The owner's bookmarks, newest first (at most MAX_SAVED_LISTED)."""
    stmt = (
        select(SavedJob.job_id, SavedJob.created_at)
        .where(SavedJob.owner_id == owner_id)
        .order_by(SavedJob.created_at.desc(), SavedJob.id.desc())
        .limit(MAX_SAVED_LISTED)
    )
    with db_engine.connect() as conn:
        return [Bookmark(job_id, saved_at) for job_id, saved_at in conn.execute(stmt).all()]


def save(owner_id: str, job_id: int, db_engine: Engine = engine) -> Bookmark | None:
    """Bookmark a job (saving it again keeps the first time); None if the job does not exist."""
    insert_stmt = (
        insert(SavedJob)
        .from_select(
            ["owner_id", "job_id"],
            select(literal(owner_id, Text), Job.id).where(Job.id == job_id),
        )
        .on_conflict_do_nothing(index_elements=["owner_id", "job_id"])
    )
    read_stmt = select(SavedJob.created_at).where(
        SavedJob.owner_id == owner_id, SavedJob.job_id == job_id
    )
    with db_engine.begin() as conn:
        conn.execute(insert_stmt)
        saved_at = conn.execute(read_stmt).scalar_one_or_none()
    return None if saved_at is None else Bookmark(job_id, saved_at)


def unsave(owner_id: str, job_id: int, db_engine: Engine = engine) -> None:
    """Remove a bookmark; removing one that does not exist is not an error."""
    stmt = delete(SavedJob).where(SavedJob.owner_id == owner_id, SavedJob.job_id == job_id)
    with db_engine.begin() as conn:
        conn.execute(stmt)
