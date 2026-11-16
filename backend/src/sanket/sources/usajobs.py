import logging
from datetime import date, timedelta
from typing import Any

from pydantic import SecretStr

from sanket.sources.base import (
    FetchResult,
    NormalizedPosting,
    SourceNotConfiguredError,
    convert_items,
)
from sanket.sources.fields import clean_text, join_nonempty, parse_iso_datetime, salary_text
from sanket.sources.http import BudgetExceededError, Fetcher

HOST = "data.usajobs.gov"
URL = f"https://{HOST}/api/Search"
PAGE_SIZE = 500
MAX_PAGES = 5
DATE_POSTED_DAYS = 2
PAGE_DELAY_SECONDS = 1.0
# A run is at most MAX_PAGES requests; this leaves room for a few runs and retries a day.
MAX_REQUESTS_PER_DAY = 40

logger = logging.getLogger(__name__)


class UsaJobsSource:
    """USAJOBS Search API: federal jobs open to the public, posted in the last 2 days.

    Needs a free API key and the email address it was registered with (sent as the
    User-Agent); without both the source is skipped and makes no request. Terms
    (developer.usajobs.gov, Terms of Service): Public Data may be copied, stored,
    reformatted, adapted, analyzed, published, redistributed and used for lawful
    commercial or non-commercial purposes, and OPM approval is not required. Naming USAJOBS
    as the source and the date the data was retrieved is encouraged (the posting's
    first/last seen time records that), and a product must not claim OPM endorsement.
    The key and the email are never logged.
    """

    name = "usajobs"
    max_requests_per_day: int | None = MAX_REQUESTS_PER_DAY
    max_attempts = 3
    min_interval: timedelta | None = timedelta(hours=1)

    def __init__(self, api_key: SecretStr | None, user_agent_email: str | None) -> None:
        self.api_key = api_key
        self.user_agent_email = (user_agent_email or "").strip() or None

    def fetch(self, http: Fetcher) -> FetchResult:
        headers = self._headers()
        items, skipped = fetch_items(http, headers)
        postings, failed = convert_items(self.name, items, to_posting)
        return FetchResult(postings, failed=failed, skipped=skipped)

    def _headers(self) -> dict[str, str]:
        key = self.api_key.get_secret_value().strip() if self.api_key else ""
        if not key or not self.user_agent_email:
            raise SourceNotConfiguredError(
                "USAJOBS_API_KEY and USAJOBS_USER_AGENT_EMAIL are both needed"
            )
        return {"Host": HOST, "User-Agent": self.user_agent_email, "Authorization-Key": key}


def fetch_items(
    http: Fetcher, headers: dict[str, str], max_pages: int = MAX_PAGES
) -> tuple[list[Any], int]:
    """Read result pages in order. Returns the items and 1 if the budget cut the run short."""
    items: list[Any] = []
    for page in range(1, max_pages + 1):
        params: dict[str, str | int] = {
            "DatePosted": DATE_POSTED_DAYS,
            "ResultsPerPage": PAGE_SIZE,
            "Page": page,
            "WhoMayApply": "public",
            "Fields": "Full",
        }
        if page > 1:
            http.sleep(PAGE_DELAY_SECONDS)
        try:
            data = http.get(URL, params=params, headers=headers).json()
        except BudgetExceededError:
            if page == 1:
                raise
            logger.warning("usajobs: request budget reached after %d pages", page - 1)
            return items, 1
        result = data.get("SearchResult") or {}
        page_items = result.get("SearchResultItems") or []
        items.extend(page_items)
        if not page_items or page * PAGE_SIZE >= _as_int(result.get("SearchResultCountAll")):
            break
    return items, 0


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def _as_lines(value: object) -> str | None:
    """A section can arrive as one string or as a list of strings."""
    if isinstance(value, list):
        return "\n".join(part for part in map(_text, value) if part) or None
    return _text(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _description(descriptor: dict[str, Any]) -> str | None:
    details = (descriptor.get("UserArea") or {}).get("Details") or {}
    sections = (
        _as_lines(details.get(key))
        for key in ("JobSummary", "MajorDuties", "QualificationSummary", "Requirements")
    )
    return "\n\n".join(section for section in sections if section) or None


def _number(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


def _salary(descriptor: dict[str, Any]) -> str | None:
    """The first pay range, for example "92108-119746 Per Year"."""
    first = (descriptor.get("PositionRemuneration") or [None])[0]
    pay = first if isinstance(first, dict) else {}
    amounts = salary_text(
        _number(pay.get("MinimumRange")), _number(pay.get("MaximumRange")), None, None
    )
    return join_nonempty([amounts, pay.get("Description") or pay.get("RateIntervalCode")], " ")


def _deadline(value: str | None) -> date | None:
    parsed = parse_iso_datetime(value)
    return parsed.date() if parsed else None


def to_posting(item: dict[str, Any]) -> NormalizedPosting:
    descriptor = item["MatchedObjectDescriptor"]
    return NormalizedPosting(
        source="usajobs",
        source_id=str(item["MatchedObjectId"]),
        url=descriptor["PositionURI"],
        title=clean_text(descriptor["PositionTitle"]) or "",
        raw=item,
        company=clean_text(descriptor.get("OrganizationName")),
        location=clean_text(descriptor.get("PositionLocationDisplay")),
        description=_description(descriptor),
        salary_text=_salary(descriptor),
        published_at=parse_iso_datetime(descriptor.get("PublicationStartDate")),
        deadline=_deadline(descriptor.get("ApplicationCloseDate")),
    )
