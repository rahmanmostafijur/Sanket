import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from pydantic import AwareDatetime, BaseModel

from sanket.sources.http import Fetcher

logger = logging.getLogger(__name__)


class NormalizedPosting(BaseModel):
    source: str
    source_id: str
    url: str
    title: str
    raw: dict
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary_text: str | None = None
    published_at: AwareDatetime | None = None
    deadline: date | None = None


@dataclass(frozen=True)
class FetchResult:
    """Postings from one source run.

    `failed` and `skipped` count sub-units, such as one company board, that failed or
    ran out of request budget while the rest of the source still succeeded.
    """

    postings: list[NormalizedPosting]
    failed: int = 0
    skipped: int = 0


class SourceNotConfiguredError(Exception):
    """Raised by a source that needs credentials it does not have, before any request.

    The run is reported as skipped, not failed, because leaving an optional source
    unconfigured is a normal setup.
    """


def convert_items(
    source: str, items: Iterable[dict], convert: Callable[[dict], NormalizedPosting]
) -> tuple[list[NormalizedPosting], int]:
    """Convert each item; a malformed item is logged and counted instead of failing the rest."""
    postings: list[NormalizedPosting] = []
    failed = 0
    for item in items:
        try:
            postings.append(convert(item))
        except (KeyError, TypeError, ValueError) as error:
            failed += 1
            logger.warning("%s: skipped malformed item: %r", source, error)
    return postings, failed


class Source(Protocol):
    """A job source that fetches its listings and converts them to NormalizedPosting.

    `max_requests_per_day` counts every attempt, retries included, per UTC day.
    `min_interval` is the shortest allowed gap between two runs of the source.
    """

    name: str
    max_requests_per_day: int | None
    max_attempts: int
    min_interval: timedelta | None

    def fetch(self, http: Fetcher) -> FetchResult: ...
