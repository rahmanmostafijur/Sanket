import logging
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.fields import clean_text, join_nonempty, parse_local_datetime
from sanket.sources.http import BudgetExceededError, Fetcher

URL = "https://jobsearch.api.jobtechdev.se/search"
PAGE_SIZE = 100
PAGE_DELAY_SECONDS = 1.0
# Runs a source may make in a day (retries included) before its budget is used up.
RUN_ALLOWANCE_PER_DAY = 8
STOCKHOLM = ZoneInfo("Europe/Stockholm")
# Timestamps in the API are wall-clock time without an offset.
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
# Application details that are not personal contact data; everything else in them is dropped.
KEPT_APPLICATION_DETAILS = ("url", "via_af")
EMPLOYER_CONTACT_KEYS = ("phone_number", "email")

logger = logging.getLogger(__name__)


class JobTechSource:
    """JobTech Sweden: the Swedish Public Employment Service's JobSearch API.

    Terms: the job ads are official open data from Arbetsformedlingen, published as "free
    to use and share regardless of purpose" (data.jobtechdev.se). The name of the licence
    was not read, and no attribution rule was found; the posting still links back to its
    Platsbanken page (`webpage_url`). No key. Ads come newest first, at most
    `max_pages` pages of 100 per run. JobStream, the bulk change feed, is the alternative
    for a full copy and is not used here.

    Personal contact data (named contacts, emails, phone numbers) is removed from `raw`.
    """

    name = "jobtech_se"
    max_requests_per_day: int | None
    max_attempts = 3
    min_interval: timedelta | None = timedelta(hours=1)

    def __init__(
        self,
        query: str | None = None,
        max_pages: int = 5,
        lookback: timedelta = timedelta(days=2),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.query = (query or "").strip() or None
        self.max_pages = max_pages
        self.lookback = lookback
        self.max_requests_per_day = max_pages * RUN_ALLOWANCE_PER_DAY
        self._clock = clock

    def fetch(self, http: Fetcher) -> FetchResult:
        published_after = (self._clock() - self.lookback).astimezone(STOCKHOLM)
        ads, skipped = fetch_ads(
            http, self.query, published_after.strftime(TIMESTAMP_FORMAT), self.max_pages
        )
        live_ads = [ad for ad in ads if not _is_removed(ad)]
        postings, failed = convert_items(self.name, live_ads, to_posting)
        return FetchResult(postings, failed=failed, skipped=skipped)


def fetch_ads(
    http: Fetcher, query: str | None, published_after: str, max_pages: int
) -> tuple[list[Any], int]:
    """Read pages newest first. Returns the ads and 1 if the budget cut the run short."""
    ads: list[Any] = []
    for page in range(max_pages):
        params: dict[str, str | int] = {
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
            "published-after": published_after,
            "sort": "pubdate-desc",
        }
        if query:
            params["q"] = query
        if page:
            http.sleep(PAGE_DELAY_SECONDS)
        try:
            data = http.get(URL, params=params).json()
        except BudgetExceededError:
            if page == 0:
                raise
            logger.warning("jobtech_se: request budget reached after %d pages", page)
            return ads, 1
        hits = data.get("hits") or []
        ads.extend(hits)
        total = (data.get("total") or {}).get("value") or 0
        if len(hits) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
            break
    return ads, 0


def _is_removed(ad: object) -> bool:
    return isinstance(ad, dict) and ad.get("removed") is True


def redact_personal_data(ad: dict[str, Any]) -> dict[str, Any]:
    """A copy of the ad without named contacts, emails, phone numbers or free-text details."""
    clean = deepcopy(ad)
    clean.pop("application_contacts", None)
    details = clean.get("application_details")
    if isinstance(details, dict):
        clean["application_details"] = {
            key: value for key, value in details.items() if key in KEPT_APPLICATION_DETAILS
        }
    employer = clean.get("employer")
    if isinstance(employer, dict):
        clean["employer"] = {k: v for k, v in employer.items() if k not in EMPLOYER_CONTACT_KEYS}
    return clean


def _location(ad: dict[str, Any]) -> str | None:
    address = ad.get("workplace_address") or {}
    return join_nonempty(address.get(key) for key in ("municipality", "region", "country"))


def _salary(ad: dict[str, Any]) -> str | None:
    # salary_type.label is only the pay type ("fixed monthly pay"), not an amount, so it is
    # left out: it would read as a salary to the extraction model.
    return clean_text(ad.get("salary_description"))


def _deadline(value: str | None) -> date | None:
    """The deadline is a local wall-clock time, so its date is the date as written."""
    parsed = parse_local_datetime(value, STOCKHOLM)
    return parsed.astimezone(STOCKHOLM).date() if parsed else None


def to_posting(ad: dict[str, Any]) -> NormalizedPosting:
    employer = ad.get("employer") or {}
    description = ad.get("description") or {}
    return NormalizedPosting(
        source="jobtech_se",
        source_id=str(ad["id"]),
        url=ad["webpage_url"],
        title=clean_text(ad["headline"]) or "",
        raw=redact_personal_data(ad),
        company=clean_text(employer.get("name")),
        location=_location(ad),
        description=description.get("text") or None,
        salary_text=_salary(ad),
        published_at=parse_local_datetime(ad.get("publication_date"), STOCKHOLM),
        deadline=_deadline(ad.get("application_deadline")),
    )
