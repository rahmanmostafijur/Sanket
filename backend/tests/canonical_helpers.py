"""Helpers that seed and read postings and jobs for canonicalisation tests."""

from datetime import UTC, datetime, timedelta
from itertools import count

from sqlalchemy import Engine, Row, delete, insert, select, update

from sanket.models import Job, Posting

BASE_TIME = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

_source_ids = count(1)


def at(days: int) -> datetime:
    return BASE_TIME + timedelta(days=days)


def add_posting(
    engine: Engine,
    *,
    source: str = "greenhouse",
    title: str | None = "Backend Engineer",
    company: str | None = "Acme",
    location: str | None = "Berlin",
    description: str | None = "<p>Build APIs.</p>",
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
) -> int:
    values: dict[str, object] = {
        "source": source,
        "source_id": f"id-{next(_source_ids)}",
        "raw": {},
        "content_hash": "h1",
        "title": title,
        "company": company,
        "location": location,
        "description": description,
    }
    if first_seen is not None:
        values["first_seen_at"] = first_seen
    if last_seen is not None:
        values["last_seen_at"] = last_seen
    with engine.begin() as conn:
        return conn.execute(insert(Posting).values(**values).returning(Posting.id)).scalar_one()


def set_posting(engine: Engine, posting_id: int, **values: object) -> None:
    with engine.begin() as conn:
        conn.execute(update(Posting).where(Posting.id == posting_id).values(**values))


def remove_posting(engine: Engine, posting_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(Posting).where(Posting.id == posting_id))


def job_of(engine: Engine, posting_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(select(Posting.job_id).where(Posting.id == posting_id)).scalar_one()


def all_jobs(engine: Engine) -> list[Row]:
    with engine.connect() as conn:
        return list(conn.execute(select(Job).order_by(Job.id)))


def get_job(engine: Engine, job_id: int) -> Row:
    with engine.connect() as conn:
        return conn.execute(select(Job).where(Job.id == job_id)).one()


def posting_links(engine: Engine) -> dict[int, int | None]:
    with engine.connect() as conn:
        return {pid: job for pid, job in conn.execute(select(Posting.id, Posting.job_id))}
