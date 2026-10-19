import logging
from datetime import UTC, datetime

import httpx

from sanket.sources.base import NormalizedPosting

URL = "https://remotive.com/api/remote-jobs"
USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"

logger = logging.getLogger(__name__)


def fetch_remotive_jobs() -> list[dict]:
    response = httpx.get(
        URL,
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(10.0, connect=5.0),
    )
    response.raise_for_status()
    data = response.json()

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
