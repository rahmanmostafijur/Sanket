import logging
from datetime import timedelta

from pydantic import SecretStr

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.fields import clean_text, from_epoch_seconds, salary_text
from sanket.sources.http import BudgetExceededError, Fetcher

URL = "https://himalayas.app/jobs/api"
PAGE_SIZE = 20
# The feed is ordered by last update, so an updated old job can come before newer jobs.
# Stopping at the first job already stored would miss those, so a page cap bounds the run.
MAX_PAGES = 50
PAGE_DELAY_SECONDS = 1.0
NO_RESTRICTIONS = "Worldwide"

logger = logging.getLogger(__name__)


class HimalayasSource:
    """Himalayas public jobs API.

    Data refreshes every 24 hours, so this runs at most once a day. Terms: apply via
    `applicationLink`, credit Himalayas with a link, do not pass jobs on to other boards
    or aggregators, and remove jobs once they expire.
    """

    name = "himalayas"
    max_requests_per_day: int | None = MAX_PAGES + 10
    max_attempts = 3
    min_interval: timedelta | None = timedelta(hours=20)

    def __init__(self, api_key: SecretStr | None = None) -> None:
        self.api_key = api_key

    def fetch(self, http: Fetcher) -> FetchResult:
        items, skipped = fetch_himalayas_jobs(http, self._headers())
        postings, failed = convert_items(self.name, items, to_posting)
        return FetchResult(postings, failed=failed, skipped=skipped)

    def _headers(self) -> dict[str, str]:
        if self.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}


def fetch_himalayas_jobs(
    http: Fetcher, headers: dict[str, str], max_pages: int = MAX_PAGES
) -> tuple[list[dict], int]:
    """Walk the browse feed by cursor. Returns the jobs and 1 if the budget cut it short."""
    jobs: list[dict] = []
    cursor: str | None = None
    for page in range(max_pages):
        params: dict[str, str | int] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
            http.sleep(PAGE_DELAY_SECONDS)
        try:
            data = http.get(URL, params=params, headers=headers).json()
        except BudgetExceededError:
            if page == 0:
                raise
            logger.warning("himalayas: request budget reached after %d pages", page)
            return jobs, 1
        jobs.extend(data.get("jobs") or [])
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return jobs, 0


def to_posting(item: dict) -> NormalizedPosting:
    restrictions = item.get("locationRestrictions") or []
    return NormalizedPosting(
        source="himalayas",
        source_id=item["guid"],
        url=item.get("applicationLink") or item["guid"],
        title=clean_text(item["title"]) or "",
        raw=item,
        company=clean_text(item.get("companyName")),
        location=", ".join(restrictions) if restrictions else NO_RESTRICTIONS,
        description=item.get("description") or None,
        salary_text=salary_text(
            item.get("minSalary"),
            item.get("maxSalary"),
            item.get("currency"),
            item.get("salaryPeriod"),
        ),
        published_at=from_epoch_seconds(item.get("pubDate")),
    )
