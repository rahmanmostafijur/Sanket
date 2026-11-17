"""Per-source request budget kept in the database, so it holds across stateless CI runs."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import Engine, func, insert, select, text

from sanket.db import engine
from sanket.models import SourceRequest
from sanket.sources.http import BudgetExceededError


def utc_now() -> datetime:
    return datetime.now(UTC)


def start_of_utc_day(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class DbRequestBudget:
    """Counts every request attempt per source per UTC day in `source_request`.

    A source without a limit is still recorded, so its last run time is known.
    """

    def __init__(
        self,
        limits: Mapping[str, int | None],
        db_engine: Engine = engine,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._limits = dict(limits)
        self._engine = db_engine
        self._now = now

    def spend(self, source: str) -> None:
        moment = self._now()
        limit = self._limits.get(source)
        with self._engine.begin() as conn:
            # Serialise spends for one source so two runs cannot both take the last slot.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:s))"), {"s": source})
            if limit is not None:
                used = conn.scalar(
                    select(func.count())
                    .select_from(SourceRequest)
                    .where(
                        SourceRequest.source == source,
                        SourceRequest.requested_at >= start_of_utc_day(moment),
                    )
                )
                if (used or 0) >= limit:
                    raise BudgetExceededError(
                        f"{source}: daily request budget of {limit} is used up"
                    )
            conn.execute(insert(SourceRequest).values(source=source, requested_at=moment))

    def last_request_at(self, source: str) -> datetime | None:
        stmt = select(func.max(SourceRequest.requested_at)).where(SourceRequest.source == source)
        with self._engine.connect() as conn:
            return conn.scalar(stmt)
