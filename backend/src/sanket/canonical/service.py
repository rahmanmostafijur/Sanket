"""Group postings into canonical jobs.

`canonicalise` scans every posting in id order, in batches (one transaction per batch, so an
interrupted run loses nothing and can simply be started again). A posting needs work when
it has no job, or when the fingerprint recomputed from its current title, company and
location differs from the fingerprint of the job it points at. Such a posting is attached
to the job with its fingerprint (created on first use), then the aggregates of every job
that gained or lost a posting are refreshed, including the job it moved away from. A
posting that no longer has a usable title or company is detached.

A job that loses its last posting is kept with a count of 0, so ids that other tables refer
to stay valid. After the posting pass, jobs whose count or seen-times drifted (postings are
re-seen on every ingest) are resynced. A second run with no new data changes nothing.

The default is a dry run, which only reads. `canonicalise_postings` does the same for a
given list of posting ids, for callers that know which postings they just wrote.
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, Row, Select, bindparam, select, update

from sanket.canonical.jobs import (
    UpsertedJob,
    find_jobs,
    find_stale_jobs,
    refresh_jobs,
    upsert_jobs,
)
from sanket.canonical.plan import Plan, PostingSnapshot, plan_batch
from sanket.db import engine
from sanket.models import Job, Posting

PostingRow = Row[int, int | None, str | None, str | None, str | None, str]
PostingQuery = Select[int, int | None, str | None, str | None, str | None, str]

DEFAULT_BATCH_SIZE = 500
POSTING_ID_PARAM = "target_posting_id"
JOB_ID_PARAM = "target_job_id"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CanonicaliseSummary:
    scanned: int = 0
    linked: int = 0
    moved: int = 0
    unlinked: int = 0
    unchanged: int = 0
    no_fingerprint: int = 0
    jobs_created: int = 0
    jobs_refreshed: int = 0
    jobs_resynced: int = 0
    applied: bool = False

    @property
    def changes(self) -> int:
        return (
            self.linked
            + self.moved
            + self.unlinked
            + self.jobs_created
            + self.jobs_refreshed
            + self.jobs_resynced
        )

    def line(self) -> str:
        mode = "apply" if self.applied else "dry-run"
        return (
            f"canonicalise mode={mode} scanned={self.scanned} linked={self.linked} "
            f"moved={self.moved} unlinked={self.unlinked} unchanged={self.unchanged} "
            f"no_fingerprint={self.no_fingerprint} jobs_created={self.jobs_created} "
            f"jobs_refreshed={self.jobs_refreshed} jobs_resynced={self.jobs_resynced}"
        )


@dataclass
class _Run:
    """Totals of one run, built up batch by batch. Internal to this module."""

    apply: bool
    scanned: int = 0
    linked: int = 0
    moved: int = 0
    unlinked: int = 0
    unchanged: int = 0
    no_fingerprint: int = 0
    jobs_created: int = 0
    resynced: int = 0
    # Apply mode: ids of jobs whose aggregates changed. Dry run: the existing jobs that
    # would be touched, plus the fingerprints of jobs that would be created.
    refreshed_ids: set[int] = field(default_factory=set)
    new_fingerprints: set[str] = field(default_factory=set)

    def absorb(self, plan: Plan, scanned: int) -> None:
        self.scanned += scanned
        self.linked += plan.linked
        self.moved += plan.moved
        self.unlinked += plan.unlinked
        self.unchanged += plan.unchanged
        self.no_fingerprint += plan.no_fingerprint

    def summary(self) -> CanonicaliseSummary:
        return CanonicaliseSummary(
            scanned=self.scanned,
            linked=self.linked,
            moved=self.moved,
            unlinked=self.unlinked,
            unchanged=self.unchanged,
            no_fingerprint=self.no_fingerprint,
            jobs_created=self.jobs_created,
            jobs_refreshed=len(self.refreshed_ids) + len(self.new_fingerprints),
            jobs_resynced=self.resynced,
            applied=self.apply,
        )


@contextmanager
def _session(db_engine: Engine, apply: bool) -> Iterator[Connection]:
    """A committing transaction when applying, otherwise a plain read that is never committed."""
    if apply:
        with db_engine.begin() as conn:
            yield conn
    else:
        with db_engine.connect() as conn:
            yield conn


def _select_postings(
    *,
    after_id: int | None = None,
    ids: Sequence[int] | None = None,
    limit: int | None = None,
    lock: bool = False,
) -> PostingQuery:
    stmt = (
        select(
            Posting.id,
            Posting.job_id,
            Posting.title,
            Posting.company,
            Posting.location,
            Job.fingerprint.label("current_fingerprint"),
        )
        .select_from(Posting)
        .outerjoin(Job, Job.id == Posting.job_id)
        .order_by(Posting.id)
    )
    if after_id is not None:
        stmt = stmt.where(Posting.id > after_id)
    if ids is not None:
        stmt = stmt.where(Posting.id.in_(ids))
    if limit is not None:
        stmt = stmt.limit(limit)
    # Concurrent runs queue on the postings they share instead of racing, and read the
    # latest job_id once the other run commits.
    return stmt.with_for_update(of=Posting) if lock else stmt


def _snapshots(rows: Sequence[PostingRow]) -> list[PostingSnapshot]:
    return [
        PostingSnapshot(
            id=row.id,
            job_id=row.job_id,
            title=row.title,
            company=row.company,
            location=row.location,
            current_fingerprint=row.current_fingerprint,
        )
        for row in rows
    ]


def _write_links(conn: Connection, plan: Plan, jobs: dict[str, UpsertedJob]) -> None:
    params = [
        {POSTING_ID_PARAM: posting_id, JOB_ID_PARAM: jobs[fp].id}
        for posting_id, fp in plan.assignments.items()
    ] + [{POSTING_ID_PARAM: posting_id, JOB_ID_PARAM: None} for posting_id in plan.detach]
    if not params:
        return
    stmt = update(Posting).where(Posting.id == bindparam(POSTING_ID_PARAM))
    conn.execute(stmt.values(job_id=bindparam(JOB_ID_PARAM)), params)


def _apply_plan(conn: Connection, plan: Plan, run: _Run) -> None:
    jobs = upsert_jobs(conn, plan.seeds)
    run.jobs_created += sum(job.created for job in jobs.values())
    _write_links(conn, plan, jobs)
    touched = {job.id for job in jobs.values()} | plan.old_job_ids
    run.refreshed_ids |= refresh_jobs(conn, touched)


def _preview_plan(conn: Connection, plan: Plan, run: _Run) -> None:
    existing = find_jobs(conn, [seed.fingerprint for seed in plan.seeds])
    for seed in plan.seeds:
        if seed.fingerprint not in existing and seed.fingerprint not in run.new_fingerprints:
            run.new_fingerprints.add(seed.fingerprint)
            run.jobs_created += 1
    run.refreshed_ids |= set(existing.values()) | plan.old_job_ids


def _process(conn: Connection, rows: Sequence[PostingRow], run: _Run) -> None:
    plan = plan_batch(_snapshots(rows))
    run.absorb(plan, len(rows))
    if run.apply:
        _apply_plan(conn, plan, run)
    else:
        _preview_plan(conn, plan, run)


def _resync(db_engine: Engine, batch_size: int, run: _Run) -> None:
    """Refresh jobs whose count or seen-times drifted since their last refresh."""
    last_id = 0
    while True:
        with _session(db_engine, run.apply) as conn:
            ids = list(
                conn.scalars(
                    select(Job.id).where(Job.id > last_id).order_by(Job.id).limit(batch_size)
                )
            )
            if not ids:
                return
            if run.apply:
                run.resynced += len(refresh_jobs(conn, ids, resync_only=True))
            else:
                run.resynced += len(find_stale_jobs(conn, ids) - run.refreshed_ids)
            last_id = ids[-1]


def canonicalise(
    db_engine: Engine = engine, batch_size: int = DEFAULT_BATCH_SIZE, apply: bool = False
) -> CanonicaliseSummary:
    """Canonicalise every posting. Without `apply` nothing is written."""
    run = _Run(apply=apply)
    last_id = 0
    while True:
        with _session(db_engine, apply) as conn:
            rows = conn.execute(
                _select_postings(after_id=last_id, limit=batch_size, lock=apply)
            ).all()
            if not rows:
                break
            _process(conn, rows, run)
            last_id = rows[-1].id
    _resync(db_engine, batch_size, run)
    return run.summary()


def canonicalise_postings(
    posting_ids: Sequence[int],
    db_engine: Engine = engine,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> CanonicaliseSummary:
    """Canonicalise just these postings and write the result.

    Meant to be called right after ingestion or extraction with the ids they touched. Ids
    that do not exist are ignored. Drifted jobs elsewhere are left to the full run.
    """
    run = _Run(apply=True)
    ids = sorted(set(posting_ids))
    for start in range(0, len(ids), batch_size):
        chunk = ids[start : start + batch_size]
        with _session(db_engine, True) as conn:
            rows = conn.execute(_select_postings(ids=chunk, lock=True)).all()
            _process(conn, rows, run)
    return run.summary()
