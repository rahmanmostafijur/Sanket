"""Read the matches of a profile, paged by match id.

Matches come in ascending id order and a page is "everything with an id after `after_id`":
remember the last id you saw and ask again with it, and no match is skipped or repeated, even
while new ones arrive. A match keeps its id when it is rescored in place, so a client that
already saw it is not shown it again; its current score and status are read when it is next
fetched by profile (without `after_id`). The live feed uses the same ids as event ids.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select

from sanket.db import engine
from sanket.models import JobMatch, MatchStatus
from sanket.search.details import JobDetails, load_details


@dataclass(frozen=True)
class MatchItem:
    id: int
    job_id: int
    score: float
    status: str
    components: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    # None when the job is gone (deleted between the two reads).
    job: JobDetails | None


@dataclass(frozen=True)
class MatchPage:
    items: list[MatchItem]
    # Pass this as `after_id` to get the next page; None when the page is empty.
    next_after_id: int | None
    has_more: bool


def list_matches(
    profile_id: int,
    *,
    after_id: int,
    limit: int,
    include_withdrawn: bool = False,
    db_engine: Engine = engine,
) -> MatchPage:
    """Matches of `profile_id` with an id above `after_id`, ascending, at most `limit`.

    The caller has already checked that the profile belongs to the owner.
    """
    stmt = select(JobMatch).where(JobMatch.profile_id == profile_id, JobMatch.id > after_id)
    if not include_withdrawn:
        stmt = stmt.where(JobMatch.status == MatchStatus.ACTIVE)
    stmt = stmt.order_by(JobMatch.id).limit(limit + 1)
    with db_engine.connect() as conn:
        rows = list(conn.execute(stmt))
    items = _items(rows[:limit], db_engine)
    return MatchPage(items, items[-1].id if items else None, has_more=len(rows) > limit)


def get_active_matches(
    profile_id: int, match_ids: Sequence[int], db_engine: Engine = engine
) -> list[MatchItem]:
    """The active matches of `profile_id` among `match_ids`, ascending by id.

    Ids of other profiles, of withdrawn matches and of rows that do not exist are left out.
    """
    if not match_ids:
        return []
    stmt = (
        select(JobMatch)
        .where(
            JobMatch.profile_id == profile_id,
            JobMatch.id.in_(match_ids),
            JobMatch.status == MatchStatus.ACTIVE,
        )
        .order_by(JobMatch.id)
    )
    with db_engine.connect() as conn:
        rows = list(conn.execute(stmt))
    return _items(rows, db_engine)


def latest_match_id(profile_id: int, db_engine: Engine = engine) -> int:
    """The highest match id of the profile (withdrawn ones included), 0 when it has none."""
    stmt = select(func.max(JobMatch.id)).where(JobMatch.profile_id == profile_id)
    with db_engine.connect() as conn:
        return int(conn.execute(stmt).scalar() or 0)


def _items(rows: Sequence[Any], db_engine: Engine) -> list[MatchItem]:
    details = load_details([row.job_id for row in rows], db_engine)
    return [
        MatchItem(
            id=row.id,
            job_id=row.job_id,
            score=row.score,
            status=row.status,
            components=row.components,
            created_at=row.created_at,
            updated_at=row.updated_at,
            job=details.get(row.job_id),
        )
        for row in rows
    ]
