from collections.abc import Sequence
from datetime import timedelta

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.boards import collect_boards, valid_slugs
from sanket.sources.fields import clean_text, parse_iso_datetime
from sanket.sources.http import Fetcher

URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseSource:
    """Public Greenhouse job boards, one request per configured company per run.

    No published rate limit or third-party terms; the content belongs to each employer.
    Always link back to `absolute_url`.
    """

    name = "greenhouse"
    max_requests_per_day: int | None = 200
    max_attempts = 3
    min_interval: timedelta | None = None

    def __init__(self, boards: Sequence[str]) -> None:
        self.boards = valid_slugs(self.name, boards)

    def fetch(self, http: Fetcher) -> FetchResult:
        return collect_boards(self.name, self.boards, lambda board: fetch_board(http, board))


def fetch_board(http: Fetcher, board: str) -> list[NormalizedPosting]:
    data = http.get(URL_TEMPLATE.format(board=board), params={"content": "true"}).json()
    postings, _ = convert_items(
        f"greenhouse/{board}", data.get("jobs") or [], lambda item: to_posting(board, item)
    )
    return postings


def to_posting(board: str, item: dict) -> NormalizedPosting:
    location = item.get("location") or {}
    return NormalizedPosting(
        source="greenhouse",
        source_id=f"{board}:{item['id']}",
        url=item["absolute_url"],
        title=clean_text(item["title"]) or "",
        raw=item,
        company=clean_text(item.get("company_name")),
        location=clean_text(location.get("name")),
        # The list endpoint returns the HTML entity-encoded, so decode it once.
        description=clean_text(item.get("content")),
        published_at=parse_iso_datetime(item.get("first_published")),
    )
