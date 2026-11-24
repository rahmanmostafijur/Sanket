"""Jobs without a search query: the newest (or oldest) listed jobs, a date ordering for
search results, and the full view of one job.

All three read the same live-job rules as search (`restrict_to_live_jobs`): a job with no
postings left is not listed and has no detail view.
"""

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Engine, func, select

from sanket.db import engine
from sanket.indexing.filters import SearchFilters, posted_at, restrict_to_live_jobs
from sanket.models import Job, Posting
from sanket.search.details import JobDetails, load_details

BLOCK_TAGS = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6]|/tr|/ul|/ol)\b[^>]*>", re.IGNORECASE)
LIST_ITEM = re.compile(r"<\s*li\b[^>]*>", re.IGNORECASE)
ANY_TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"[ \t\r\f\v]+")
BLANK_LINES = re.compile(r"\n\s*\n+")
LIST_MARKER = "-"


class BrowseSort(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"


@dataclass(frozen=True)
class JobPage:
    total: int
    jobs: list[JobDetails]


@dataclass(frozen=True)
class PostingRef:
    source: str
    url: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class JobView:
    details: JobDetails
    description: str | None
    postings: list[PostingRef]


def list_jobs(
    filters: SearchFilters,
    sort: BrowseSort,
    *,
    limit: int,
    offset: int,
    db_engine: Engine = engine,
) -> JobPage:
    """One page of live jobs that pass `filters`, by posting date (ties by id)."""
    when = posted_at()
    order = (when.desc(), Job.id.desc()) if sort is BrowseSort.NEWEST else (when, Job.id)
    ids_stmt = restrict_to_live_jobs(select(Job.id), filters).order_by(*order)
    count_stmt = select(func.count()).select_from(
        restrict_to_live_jobs(select(Job.id), filters).subquery()
    )
    with db_engine.connect() as conn:
        total = int(conn.execute(count_stmt).scalar_one())
        ids = list(conn.execute(ids_stmt.limit(limit).offset(offset)).scalars())
    details = load_details(ids, db_engine)
    return JobPage(total=total, jobs=[details[job_id] for job_id in ids if job_id in details])


def newest_first(job_ids: Sequence[int], db_engine: Engine = engine) -> list[int]:
    """The given job ids ordered by posting date, newest first (ties by id)."""
    if not job_ids:
        return []
    stmt = (
        select(Job.id).where(Job.id.in_(list(job_ids))).order_by(posted_at().desc(), Job.id.desc())
    )
    with db_engine.connect() as conn:
        return list(conn.execute(stmt).scalars())


def plain_text(markup: str | None) -> str | None:
    """Posting descriptions arrive as HTML or text; return readable plain text, never markup."""
    if not markup:
        return None
    text = LIST_ITEM.sub(f"\n{LIST_MARKER} ", BLOCK_TAGS.sub("\n", markup))
    text = html.unescape(ANY_TAG.sub("", text))
    lines = [SPACES.sub(" ", line).strip() for line in text.split("\n")]
    cleaned = BLANK_LINES.sub("\n\n", "\n".join(_attach_markers(lines))).strip()
    return cleaned or None


def _attach_markers(lines: list[str]) -> list[str]:
    """Join a list marker left on a line of its own (markup such as `<li>\\n<p>Text`) to the
    item's text on the next non-empty line; drop a marker with no text before the next item."""
    out: list[str] = []
    pending = False
    for line in lines:
        if line == LIST_MARKER:
            pending = True
        elif pending and line:
            out.append(line if line.startswith(f"{LIST_MARKER} ") else f"{LIST_MARKER} {line}")
            pending = False
        elif not pending:
            out.append(line)
    return out


def load_job(job_id: int, db_engine: Engine = engine) -> JobView | None:
    """The full view of a live job, or None if it does not exist or has no postings."""
    live = restrict_to_live_jobs(select(Job.id), SearchFilters()).where(Job.id == job_id)
    description_stmt = (
        select(Posting.description)
        .join(Job, Job.representative_posting_id == Posting.id)
        .where(Job.id == job_id)
    )
    postings_stmt = (
        select(Posting.source, Posting.url, Posting.published_at)
        .where(Posting.job_id == job_id)
        .order_by(Posting.published_at.desc().nulls_last(), Posting.id)
    )
    with db_engine.connect() as conn:
        if conn.execute(live).first() is None:
            return None
        description = conn.execute(description_stmt).scalar_one_or_none()
        postings = [PostingRef(*row) for row in conn.execute(postings_stmt).all()]
    details = load_details([job_id], db_engine).get(job_id)
    if details is None:
        return None
    return JobView(details=details, description=plain_text(description), postings=postings)
