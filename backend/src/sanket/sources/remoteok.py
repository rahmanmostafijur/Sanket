from datetime import timedelta

from ftfy import fix_encoding

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.http import Fetcher

URL = "https://remoteok.com/api"
ANTI_SPAM_MARKER = "Please mention the word"


class RemoteOkSource:
    """Remote OK public API. Terms: link back (do-follow) and name "Remote OK" as source."""

    name = "remoteok"
    max_requests_per_day: int | None = 12
    max_attempts = 3
    min_interval: timedelta | None = None

    def fetch(self, http: Fetcher) -> FetchResult:
        postings, failed = convert_items(self.name, fetch_remoteok_jobs(http), to_posting)
        return FetchResult(postings, failed=failed)


def fetch_remoteok_jobs(http: Fetcher) -> list[dict]:
    data = http.get(URL).json()
    # The first element is the API legal notice, not a job. Anything else that is not a
    # JSON object cannot be a job either.
    return [item for item in data if isinstance(item, dict) and "id" in item]


def _fix_encoding(text: str | None) -> str | None:
    if text is None:
        return None
    return fix_encoding(text)


def to_posting(item: dict) -> NormalizedPosting:
    description = _strip_anti_spam(item.get("description") or "") or None
    return NormalizedPosting(
        source="remoteok",
        source_id=item["id"],
        url=item["url"],
        # A missing position gives None, which pydantic rejects so the item is skipped.
        title=_fix_encoding(item["position"]),  # type: ignore[arg-type]
        raw=item,
        company=_fix_encoding(item.get("company")) or None,
        location=_fix_encoding(item.get("location")) or None,
        description=_fix_encoding(description),
        published_at=item.get("date") or None,
        salary_text=_salary_text(item),
    )


def _strip_anti_spam(text: str) -> str:
    index = text.rfind(ANTI_SPAM_MARKER)
    if index == -1:
        return text
    return text[:index].rstrip()


def _salary_text(item: dict) -> str | None:
    low = item.get("salary_min") or 0
    high = item.get("salary_max") or 0
    if low == 0 and high == 0:
        return None
    return f"{low}-{high} USD"
