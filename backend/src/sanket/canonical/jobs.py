"""Database operations on `job`: race-safe upsert by fingerprint and aggregate refresh."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    ColumnElement,
    Connection,
    Subquery,
    and_,
    case,
    func,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import aliased

from sanket.canonical.plan import JobSeed
from sanket.models import Job, Posting


@dataclass(frozen=True)
class UpsertedJob:
    id: int
    created: bool


def upsert_jobs(conn: Connection, seeds: Sequence[JobSeed]) -> dict[str, UpsertedJob]:
    """Insert the jobs that do not exist yet and return every fingerprint's job id.

    `ON CONFLICT (fingerprint) DO UPDATE` makes concurrent runs safe: whoever loses the race
    waits for the winner's insert and then reads its row instead of creating a second one.
    The update is a no-op (the fingerprint is set to itself) that exists only so the existing
    row is returned. `xmax = 0` tells a fresh insert from a conflict. Rows are sent sorted by
    fingerprint so that concurrent runs take their locks in the same order.
    """
    unique = {seed.fingerprint: seed for seed in seeds}
    if not unique:
        return {}
    rows = [
        {
            "fingerprint": seed.fingerprint,
            "title": seed.title,
            "company": seed.company,
            "location": seed.location,
        }
        for _, seed in sorted(unique.items())
    ]
    insert_stmt = insert(Job).values(rows)
    upsert = insert_stmt.on_conflict_do_update(
        index_elements=[Job.fingerprint], set_={"fingerprint": insert_stmt.excluded.fingerprint}
    )
    created = literal_column("(xmax = 0)", Boolean).label("created")
    stmt = upsert.returning(Job.id, Job.fingerprint, created)
    return {row.fingerprint: UpsertedJob(row.id, row.created) for row in conn.execute(stmt)}


def find_jobs(conn: Connection, fingerprints: Collection[str]) -> dict[str, int]:
    """The ids of the jobs that already exist for these fingerprints."""
    if not fingerprints:
        return {}
    stmt = select(Job.fingerprint, Job.id).where(Job.fingerprint.in_(fingerprints))
    return {fingerprint: job_id for fingerprint, job_id in conn.execute(stmt)}


def _targets(job_ids: Collection[int]) -> Subquery:
    """What each job's aggregates should be, computed from its current postings.

    The representative posting is the best member: one with a description first, then the
    most recently seen, then the lowest id. Its title, company and location become the
    display fields. A job with no postings (or no member with a title and company) keeps its
    previous values, with a count of 0 and no representative.
    """
    current = aliased(Job)
    members = Posting.job_id.in_(job_ids)
    totals = (
        select(
            Posting.job_id.label("job_id"),
            func.count(Posting.id).label("posting_count"),
            func.min(Posting.first_seen_at).label("first_seen_at"),
            func.max(Posting.last_seen_at).label("last_seen_at"),
        )
        .where(members)
        .group_by(Posting.job_id)
        .subquery("totals")
    )
    has_description = func.btrim(func.coalesce(Posting.description, "")) != ""
    best = (
        select(
            Posting.job_id.label("job_id"),
            Posting.id.label("posting_id"),
            Posting.title.label("title"),
            Posting.company.label("company"),
            Posting.location.label("location"),
        )
        .where(members, Posting.title.is_not(None), Posting.company.is_not(None))
        .ext(distinct_on(Posting.job_id))
        .order_by(Posting.job_id, has_description.desc(), Posting.last_seen_at.desc(), Posting.id)
        .subquery("best")
    )
    return (
        select(
            current.id.label("job_id"),
            func.coalesce(totals.c.posting_count, 0).label("posting_count"),
            func.coalesce(totals.c.first_seen_at, current.first_seen_at).label("first_seen_at"),
            func.coalesce(totals.c.last_seen_at, current.last_seen_at).label("last_seen_at"),
            best.c.posting_id.label("representative_posting_id"),
            func.coalesce(best.c.title, current.title).label("title"),
            func.coalesce(best.c.company, current.company).label("company"),
            case((best.c.posting_id.is_not(None), best.c.location), else_=current.location).label(
                "location"
            ),
        )
        .select_from(current)
        .outerjoin(totals, totals.c.job_id == current.id)
        .outerjoin(best, best.c.job_id == current.id)
        .where(current.id.in_(job_ids))
        .subquery("target")
    )


def _differs(target: Subquery, *, resync_only: bool) -> ColumnElement[bool]:
    """Whether a job's stored aggregates are out of date.

    `resync_only` checks the cheap facts that go stale on their own (count, first and last
    seen, a missing representative) and leaves the choice of representative alone, so
    postings re-seen by ingestion do not make the display fields flip between sources.
    """
    columns = target.c
    stale = or_(
        Job.posting_count.is_distinct_from(columns.posting_count),
        Job.first_seen_at.is_distinct_from(columns.first_seen_at),
        Job.last_seen_at.is_distinct_from(columns.last_seen_at),
    )
    if resync_only:
        no_representative = and_(
            Job.representative_posting_id.is_(None), columns.representative_posting_id.is_not(None)
        )
        return or_(stale, no_representative)
    return or_(
        stale,
        Job.representative_posting_id.is_distinct_from(columns.representative_posting_id),
        Job.title.is_distinct_from(columns.title),
        Job.company.is_distinct_from(columns.company),
        Job.location.is_distinct_from(columns.location),
    )


def find_stale_jobs(conn: Connection, job_ids: Collection[int]) -> frozenset[int]:
    """The jobs whose count or seen-times no longer match their postings (read only)."""
    if not job_ids:
        return frozenset()
    target = _targets(job_ids)
    stmt = select(Job.id).join(target, target.c.job_id == Job.id)
    stmt = stmt.where(_differs(target, resync_only=True))
    return frozenset(conn.scalars(stmt))


def refresh_jobs(
    conn: Connection, job_ids: Collection[int], *, resync_only: bool = False
) -> frozenset[int]:
    """Recompute the aggregates of these jobs; returns the ids that actually changed.

    Rows are locked in id order first so concurrent runs cannot deadlock on each other.
    """
    if not job_ids:
        return frozenset()
    conn.execute(select(Job.id).where(Job.id.in_(job_ids)).order_by(Job.id).with_for_update())
    target = _targets(job_ids)
    columns = target.c
    stmt = (
        update(Job)
        .where(Job.id == columns.job_id, _differs(target, resync_only=resync_only))
        .values(
            posting_count=columns.posting_count,
            first_seen_at=columns.first_seen_at,
            last_seen_at=columns.last_seen_at,
            representative_posting_id=columns.representative_posting_id,
            title=columns.title,
            company=columns.company,
            location=columns.location,
            updated_at=func.now(),
        )
        .returning(Job.id)
    )
    return frozenset(conn.scalars(stmt))
