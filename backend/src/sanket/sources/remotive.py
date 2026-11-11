import logging
from datetime import UTC, datetime, timedelta

from sanket.sources.base import FetchResult, NormalizedPosting
from sanket.sources.http import Fetcher

URL = "https://remotive.com/api/remote-jobs"

logger = logging.getLogger(__name__)


class RemotiveSource:
    """Remotive public API.

    Terms: at most 4 requests a day, link back to the Remotive URL and credit Remotive,
    and do not pass the jobs on to other job sites. One attempt per run, no retries, so a
    retry can never push the daily count over the limit.
    """

    name = "remotive"
    max_requests_per_day: int | None = 4
    max_attempts = 1
    min_interval: timedelta | None = None

    def fetch(self, http: Fetcher) -> FetchResult:
        return FetchResult([to_posting(item) for item in fetch_remotive_jobs(http)])


def fetch_remotive_jobs(http: Fetcher) -> list[dict]:
    data = http.get(URL).json()

    logger.info(
        "Fetched %d jobs from remotive (job-count=%s)",
        len(data["jobs"]),
        data.get("job-count"),
    )
    return [
        {
            **job,
            "company": job["company_name"],
            "position": job["title"],
            "location": job["candidate_required_location"],
        }
        for job in data["jobs"]
    ]


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        # Remotive sends naive timestamps; assumed to be UTC.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_posting(item: dict) -> NormalizedPosting:
    return NormalizedPosting(
        source="remotive",
        source_id=str(item["id"]),
        url=item["url"],
        title=item["title"],
        raw=item,
        company=item.get("company_name") or None,
        location=item.get("candidate_required_location") or None,
        description=item.get("description") or None,
        salary_text=item.get("salary") or None,
        published_at=_parse_published_at(item.get("publication_date")),
    )
