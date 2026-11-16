from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.boards import collect_boards, valid_slugs
from sanket.sources.fields import clean_text, parse_iso_datetime
from sanket.sources.http import Fetcher

URL_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{board}"


class AshbySource:
    """Public Ashby job boards, one request per configured company per run.

    This is Ashby's documented public posting API, which employers publish for others
    to read. No key, no published rate limit and no third-party terms; the content
    belongs to each employer, so always link back to `jobUrl`. A board is returned in one
    response, which can be several MB, so there are no extra per-job requests.
    """

    name = "ashby"
    max_requests_per_day: int | None = 200
    max_attempts = 3
    min_interval: timedelta | None = None

    def __init__(self, boards: Sequence[str]) -> None:
        self.boards = valid_slugs(self.name, boards)

    def fetch(self, http: Fetcher) -> FetchResult:
        return collect_boards(self.name, self.boards, lambda board: fetch_board(http, board))


def fetch_board(http: Fetcher, board: str) -> list[NormalizedPosting]:
    data = http.get(URL_TEMPLATE.format(board=board), params={"includeCompensation": "true"}).json()
    listed = [item for item in data.get("jobs") or [] if not _is_unlisted(item)]
    postings, _ = convert_items(f"ashby/{board}", listed, lambda item: to_posting(board, item))
    return postings


def _is_unlisted(item: object) -> bool:
    """Ashby keeps jobs that are not on the public board; a non-object is left to be counted."""
    return isinstance(item, dict) and item.get("isListed") is False


def _location(item: dict[str, Any]) -> str | None:
    location = clean_text(item.get("location"))
    if not item.get("isRemote"):
        return location
    if location is None:
        return "Remote"
    return location if "remote" in location.lower() else f"{location} (Remote)"


def _description(item: dict[str, Any]) -> str | None:
    plain = (item.get("descriptionPlain") or "").strip()
    return plain or item.get("descriptionHtml") or None


def _salary(item: dict[str, Any]) -> str | None:
    """The employer's own compensation summary, unless it chose not to show it."""
    if item.get("shouldDisplayCompensationOnJobPostings") is False:
        return None
    compensation = item.get("compensation") or {}
    return clean_text(compensation.get("compensationTierSummary")) or clean_text(
        compensation.get("scrapeableCompensationSalarySummary")
    )


def to_posting(board: str, item: dict[str, Any]) -> NormalizedPosting:
    return NormalizedPosting(
        source="ashby",
        source_id=item["id"],
        url=item["jobUrl"],
        title=clean_text(item["title"]) or "",
        raw=item,
        # The posting API has no company name, so the board slug stands in for it.
        company=board,
        location=_location(item),
        description=_description(item),
        salary_text=_salary(item),
        published_at=parse_iso_datetime(item.get("publishedAt")),
    )
