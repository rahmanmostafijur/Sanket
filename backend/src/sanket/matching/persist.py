"""Persist matches idempotently.

`plan_write` (pure) decides, from the stored row and the new evaluation, what has to be written
and whether it is a new match worth a notification:

| stored             | now passes | plan                                                       |
|--------------------|------------|------------------------------------------------------------|
| nothing            | yes        | insert active, notify                                      |
| nothing            | no         | nothing (no row for a non-match)                           |
| active             | yes        | same score, components and version: nothing (or only the   |
|                    |            | hashes, `updated_at` untouched); else update in place      |
| active             | no         | withdraw (row kept, new score and components stored)       |
| withdrawn          | yes        | back to active, `notified_at` reset, notify                |
| withdrawn          | no         | nothing                                                    |

The rows to be decided on are read `FOR UPDATE` in the same transaction as the writes, so two
workers handling the same job or profile queue up instead of both deciding "reactivate". A pair
with no row yet cannot be locked: there a first match is `INSERT ... ON CONFLICT DO NOTHING` and
only the worker whose insert took effect announces it. Other changes are
`INSERT ... ON CONFLICT (profile_id, job_id) DO UPDATE`. Only rows that change are written, so
re-running with the same inputs touches nothing: no new id, no sequence value used,
`updated_at` unchanged.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Connection, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from sanket.matching.score import SCORER_VERSION
from sanket.matching.types import MatchScore
from sanket.models import JobMatch, MatchStatus


@dataclass(frozen=True)
class Evaluation:
    """One job scored for one profile, with what it was scored against."""

    profile_id: int
    job_id: int
    score: MatchScore
    job_embedding_hash: str
    profile_hash: str


@dataclass(frozen=True)
class StoredMatch:
    id: int
    profile_id: int
    job_id: int
    score: float
    components: dict[str, Any]
    scorer_version: int
    status: str
    job_embedding_hash: str
    profile_hash: str
    notified_at: datetime | None


class WriteKind(StrEnum):
    INSERT = "insert"
    REACTIVATE = "reactivate"
    UPDATE = "update"
    HASHES = "hashes"
    WITHDRAW = "withdraw"


@dataclass(frozen=True)
class WritePlan:
    evaluation: Evaluation
    kind: WriteKind
    status: str
    notified_at: datetime | None

    @property
    def is_new(self) -> bool:
        """A first match or a reactivated one: worth a notification."""
        return self.kind in (WriteKind.INSERT, WriteKind.REACTIVATE)

    @property
    def touches_updated_at(self) -> bool:
        return self.kind is not WriteKind.HASHES


def _same_result(stored: StoredMatch, evaluation: Evaluation) -> bool:
    return (
        stored.score == evaluation.score.score
        and stored.components == evaluation.score.components
        and stored.scorer_version == SCORER_VERSION
    )


def _same_inputs(stored: StoredMatch, evaluation: Evaluation) -> bool:
    return (
        stored.job_embedding_hash == evaluation.job_embedding_hash
        and stored.profile_hash == evaluation.profile_hash
    )


def _plan_for_match(stored: StoredMatch | None, evaluation: Evaluation) -> WritePlan | None:
    if stored is None:
        return WritePlan(evaluation, WriteKind.INSERT, MatchStatus.ACTIVE, None)
    if stored.status == MatchStatus.WITHDRAWN:
        return WritePlan(evaluation, WriteKind.REACTIVATE, MatchStatus.ACTIVE, None)
    if not _same_result(stored, evaluation):
        return WritePlan(evaluation, WriteKind.UPDATE, MatchStatus.ACTIVE, stored.notified_at)
    if not _same_inputs(stored, evaluation):
        return WritePlan(evaluation, WriteKind.HASHES, MatchStatus.ACTIVE, stored.notified_at)
    return None


def plan_write(stored: StoredMatch | None, evaluation: Evaluation) -> WritePlan | None:
    """What to write for one evaluation, or None when the database is already right."""
    if evaluation.score.is_match:
        return _plan_for_match(stored, evaluation)
    if stored is not None and stored.status == MatchStatus.ACTIVE:
        return WritePlan(evaluation, WriteKind.WITHDRAW, MatchStatus.WITHDRAWN, stored.notified_at)
    return None


def load_stored_for_job(
    conn: Connection, job_id: int, profile_ids: Sequence[int]
) -> dict[tuple[int, int], StoredMatch]:
    """Lock and return the job's matches for these profiles and all its active matches."""
    stmt = (
        select(JobMatch)
        .where(
            JobMatch.job_id == job_id,
            or_(JobMatch.profile_id.in_(profile_ids), JobMatch.status == MatchStatus.ACTIVE),
        )
        .order_by(JobMatch.id)
        .with_for_update()
    )
    return _stored(conn, stmt)


def load_stored_for_profile(
    conn: Connection, profile_id: int, job_ids: Sequence[int]
) -> dict[tuple[int, int], StoredMatch]:
    """Lock and return the profile's matches for these jobs and all its active matches."""
    stmt = (
        select(JobMatch)
        .where(
            JobMatch.profile_id == profile_id,
            or_(JobMatch.job_id.in_(job_ids), JobMatch.status == MatchStatus.ACTIVE),
        )
        .order_by(JobMatch.id)
        .with_for_update()
    )
    return _stored(conn, stmt)


def _stored(conn: Connection, stmt: Any) -> dict[tuple[int, int], StoredMatch]:
    result: dict[tuple[int, int], StoredMatch] = {}
    for row in conn.execute(stmt):
        stored = StoredMatch(
            id=row.id,
            profile_id=row.profile_id,
            job_id=row.job_id,
            score=row.score,
            components=row.components,
            scorer_version=row.scorer_version,
            status=row.status,
            job_embedding_hash=row.job_embedding_hash,
            profile_hash=row.profile_hash,
            notified_at=row.notified_at,
        )
        result[(stored.profile_id, stored.job_id)] = stored
    return result


def _row_values(plan: WritePlan) -> dict[str, Any]:
    evaluation = plan.evaluation
    return {
        "profile_id": evaluation.profile_id,
        "job_id": evaluation.job_id,
        "score": evaluation.score.score,
        "components": evaluation.score.components,
        "scorer_version": SCORER_VERSION,
        "status": plan.status,
        "job_embedding_hash": evaluation.job_embedding_hash,
        "profile_hash": evaluation.profile_hash,
        "notified_at": plan.notified_at,
    }


def _upsert(
    conn: Connection, plans: Sequence[WritePlan], touch: bool
) -> dict[tuple[int, int], int]:
    if not plans:
        return {}
    base = insert(JobMatch).values([_row_values(plan) for plan in plans])
    changed = {
        name: getattr(base.excluded, name)
        for name in (
            "score",
            "components",
            "scorer_version",
            "status",
            "job_embedding_hash",
            "profile_hash",
            "notified_at",
        )
    }
    if touch:
        changed["updated_at"] = func.now()
    stmt = base.on_conflict_do_update(
        index_elements=[JobMatch.profile_id, JobMatch.job_id], set_=changed
    ).returning(JobMatch.profile_id, JobMatch.job_id, JobMatch.id)
    return {(row[0], row[1]): row[2] for row in conn.execute(stmt)}


def _insert_new(conn: Connection, plans: Sequence[WritePlan]) -> dict[tuple[int, int], int]:
    """Insert first matches; a row another worker created in the meantime is left as it is.

    `FOR UPDATE` cannot lock a row that does not exist yet, so two workers may both decide a
    pair is new. The second insert waits for the first to commit and then does nothing: only
    the rows that were really inserted are returned, so only one worker announces the match.
    """
    if not plans:
        return {}
    stmt = (
        insert(JobMatch)
        .values([_row_values(plan) for plan in plans])
        .on_conflict_do_nothing(index_elements=[JobMatch.profile_id, JobMatch.job_id])
        .returning(JobMatch.profile_id, JobMatch.job_id, JobMatch.id)
    )
    return {(row[0], row[1]): row[2] for row in conn.execute(stmt)}


def apply_plans(conn: Connection, plans: Sequence[WritePlan]) -> dict[tuple[int, int], int]:
    """Write the plans; returns the match id of every row written by (profile_id, job_id).

    An insert that lost the race to a concurrent worker writes nothing and is not returned.
    """
    ids = _insert_new(conn, [p for p in plans if p.kind is WriteKind.INSERT])
    others = [p for p in plans if p.kind is not WriteKind.INSERT]
    ids.update(_upsert(conn, [p for p in others if p.touches_updated_at], touch=True))
    ids.update(_upsert(conn, [p for p in others if not p.touches_updated_at], touch=False))
    return ids


def withdraw_matches(conn: Connection, match_ids: Sequence[int]) -> int:
    """Withdraw these matches if they are active; returns how many were."""
    if not match_ids:
        return 0
    stmt = (
        update(JobMatch)
        .where(JobMatch.id.in_(match_ids), JobMatch.status == MatchStatus.ACTIVE)
        .values(status=MatchStatus.WITHDRAWN, updated_at=func.now())
    )
    return int(conn.execute(stmt).rowcount)


def withdraw_job_matches(conn: Connection, job_ids: Sequence[int]) -> int:
    """Withdraw every active match of these jobs (they have no postings or no embedding)."""
    if not job_ids:
        return 0
    stmt = (
        update(JobMatch)
        .where(JobMatch.job_id.in_(job_ids), JobMatch.status == MatchStatus.ACTIVE)
        .values(status=MatchStatus.WITHDRAWN, updated_at=func.now())
    )
    return int(conn.execute(stmt).rowcount)


def withdraw_profile_matches(conn: Connection, profile_id: int) -> int:
    """Withdraw every active match of a profile (it was switched off)."""
    stmt = (
        update(JobMatch)
        .where(JobMatch.profile_id == profile_id, JobMatch.status == MatchStatus.ACTIVE)
        .values(status=MatchStatus.WITHDRAWN, updated_at=func.now())
    )
    return int(conn.execute(stmt).rowcount)


def mark_notified(conn: Connection, match_ids: Sequence[int]) -> None:
    """Record that the notification hook ran for these matches."""
    if not match_ids:
        return
    stmt = (
        update(JobMatch)
        .where(JobMatch.id.in_(match_ids), JobMatch.notified_at.is_(None))
        .values(notified_at=func.now())
    )
    conn.execute(stmt)
