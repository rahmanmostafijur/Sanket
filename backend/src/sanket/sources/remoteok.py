import httpx

from sanket.sources.base import NormalizedPosting

URL = "https://remoteok.com/api"
USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"
ANTI_SPAM_MARKER = "Please mention the word"


def fetch_remoteok_jobs():
    response = httpx.get(
        URL,
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(10.0, connect=5.0),
    )
    response.raise_for_status()
    data = response.json()

    jobs = [item for item in data if "id" in item]
    return jobs


def to_posting(item: dict) -> NormalizedPosting:
    description = _strip_anti_spam(item.get("description") or "") or None
    return NormalizedPosting(
        source="remoteok",
        source_id=item["id"],
        url=item["url"],
        title=item["position"],
        raw=item,
        company=item.get("company") or None,
        location=item.get("location") or None,
        description=description,
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
