import logging
from datetime import timedelta

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.fields import clean_text, parse_iso_datetime, salary_text
from sanket.sources.http import BudgetExceededError, Fetcher

URL = "https://jobicy.com/api/jobs"
PAGE_SIZE = 100
MAX_PAGES = 10

logger = logging.getLogger(__name__)


class JobicySource:
    """Jobicy public API (last 7 days of jobs).

    Terms: credit Jobicy with a link, keep apply links on the Jobicy URL, and start an
    automated pass no more than once per hour. Storage and AI analysis are allowed.
    """

    name = "jobicy"
    max_requests_per_day: int | None = 60
    max_attempts = 3
    min_interval: timedelta | None = timedelta(hours=1)

    def fetch(self, http: Fetcher) -> FetchResult:
        items, skipped = fetch_jobicy_jobs(http)
        postings, failed = convert_items(self.name, items, to_posting)
        return FetchResult(postings, failed=failed, skipped=skipped)


def fetch_jobicy_jobs(http: Fetcher, max_pages: int = MAX_PAGES) -> tuple[list[dict], int]:
    """Follow the cursor pages in order. Returns the jobs and 1 if the budget cut it short."""
    jobs: list[dict] = []
    cursor: str | None = None
    for page in range(max_pages):
        params: dict[str, str | int] = {"count": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        try:
            data = http.get(URL, params=params).json()
        except BudgetExceededError:
            if page == 0:
                raise
            logger.warning("jobicy: request budget reached after %d pages", page)
            return jobs, 1
        jobs.extend(data.get("jobs") or [])
        cursor = data.get("nextCursor")
        if not data.get("hasMore") or not cursor:
            break
    return jobs, 0


def to_posting(item: dict) -> NormalizedPosting:
    return NormalizedPosting(
        source="jobicy",
        source_id=str(item["id"]),
        url=item["url"],
        title=clean_text(item["jobTitle"]) or "",
        raw=item,
        company=clean_text(item.get("companyName")),
        location=clean_text(item.get("jobGeo")),
        description=item.get("jobDescription") or None,
        salary_text=salary_text(
            item.get("salaryMin"),
            item.get("salaryMax"),
            item.get("salaryCurrency"),
            item.get("salaryPeriod"),
        ),
        published_at=parse_iso_datetime(item.get("pubDate")),
    )
