"""What a result shows about a job: canonical fields, the representative posting and its
extraction. Loaded only for the jobs on the page being returned."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, distinct, func, select, true
from sqlalchemy.orm import aliased

from sanket.db import engine
from sanket.indexing.filters import latest_extraction_lateral
from sanket.models import Job, Posting


@dataclass(frozen=True)
class JobDetails:
    job_id: int
    title: str
    company: str
    location: str | None
    # The representative posting: where the title and link come from.
    source: str | None
    url: str | None
    published_at: datetime | None
    first_seen_at: datetime
    salary_text: str | None
    # Every source that currently lists the job (the representative one included).
    sources: tuple[str, ...]
    # The newest successful extraction of the representative posting, or None.
    extraction: dict[str, Any] | None


def load_details(job_ids: Sequence[int], db_engine: Engine = engine) -> dict[int, JobDetails]:
    """Details of the given jobs by id; ids that do not exist are absent."""
    if not job_ids:
        return {}
    extraction = latest_extraction_lateral()
    member = aliased(Posting)
    listed_on = (
        select(func.array_agg(distinct(member.source)))
        .where(member.job_id == Job.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Job.id,
            Job.title,
            Job.company,
            Job.location,
            Posting.source,
            Posting.url,
            Posting.published_at,
            Job.first_seen_at,
            Posting.salary_text,
            listed_on,
            extraction.c.data,
        )
        .select_from(Job)
        .outerjoin(Posting, Posting.id == Job.representative_posting_id)
        .join(extraction, true(), isouter=True)
        .where(Job.id.in_(list(job_ids)))
    )
    with db_engine.connect() as conn:
        rows = conn.execute(stmt).all()
    return {row[0]: _details(row) for row in rows}


def _details(row: Any) -> JobDetails:
    sources = tuple(sorted(row[9] or ()))
    return JobDetails(
        job_id=row[0],
        title=row[1],
        company=row[2],
        location=row[3],
        source=row[4],
        url=row[5],
        published_at=row[6],
        first_seen_at=row[7],
        salary_text=row[8],
        sources=sources,
        extraction=row[10],
    )
