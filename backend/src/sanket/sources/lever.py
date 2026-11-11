from collections.abc import Sequence
from datetime import timedelta

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.boards import collect_boards, valid_slugs
from sanket.sources.fields import clean_text, from_epoch_milliseconds, salary_text
from sanket.sources.http import Fetcher

URL_TEMPLATE = "https://api.lever.co/v0/postings/{company}"


class LeverSource:
    """Public Lever postings, one request per configured company per run (global instance).

    The README says published postings are public and may be read by third parties.
    The content belongs to each employer; always link back to `hostedUrl`.
    """

    name = "lever"
    max_requests_per_day: int | None = 200
    max_attempts = 3
    min_interval: timedelta | None = None

    def __init__(self, companies: Sequence[str]) -> None:
        self.companies = valid_slugs(self.name, companies)

    def fetch(self, http: Fetcher) -> FetchResult:
        return collect_boards(self.name, self.companies, lambda slug: fetch_company(http, slug))


def fetch_company(http: Fetcher, company: str) -> list[NormalizedPosting]:
    data = http.get(URL_TEMPLATE.format(company=company), params={"mode": "json"}).json()
    postings, _ = convert_items(f"lever/{company}", data, lambda item: to_posting(company, item))
    return postings


def _description(item: dict) -> str | None:
    """Lever splits a posting into an intro, titled lists, and a closing section."""
    parts = [item.get("description") or ""]
    for section in item.get("lists") or []:
        parts.append(f"<h3>{section.get('text', '')}</h3><ul>{section.get('content', '')}</ul>")
    parts.append(item.get("additional") or "")
    return "\n".join(part for part in parts if part) or None


def _salary(item: dict) -> str | None:
    salary = item.get("salaryRange") or {}
    return salary_text(
        salary.get("min"), salary.get("max"), salary.get("currency"), salary.get("interval")
    )


def to_posting(company: str, item: dict) -> NormalizedPosting:
    categories = item.get("categories") or {}
    return NormalizedPosting(
        source="lever",
        source_id=f"{company}:{item['id']}",
        url=item["hostedUrl"],
        title=clean_text(item["text"]) or "",
        raw=item,
        # The postings API has no company name, so the board slug stands in for it.
        company=company,
        location=clean_text(categories.get("location")),
        description=_description(item),
        salary_text=_salary(item),
        published_at=from_epoch_milliseconds(item.get("createdAt")),
    )
