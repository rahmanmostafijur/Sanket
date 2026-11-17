import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
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
        postings, failed = convert_items(self.name, fetch_remotive_jobs(http), to_posting)
        return FetchResult(postings, failed=failed)


def fetch_remotive_jobs(http: Fetcher) -> list[dict]:
    data = http.get(URL).json()

    logger.info(
        "Fetched %d jobs from remotive (job-count=%s)",
        len(data["jobs"]),
        data.get("job-count"),
    )
    return [_with_aliases(job) for job in data["jobs"]]


def _with_aliases(job: Any) -> Any:
    """Add the shared company/position/location keys; a missing field stays None.

    Anything that is not a JSON object is returned as is, so `to_posting` rejects it and
    it is skipped like any other malformed item.
    """
    if not isinstance(job, dict):
        return job
    return {
        **job,
        "company": job.get("company_name"),
        "position": job.get("title"),
        "location": job.get("candidate_required_location"),
    }


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
