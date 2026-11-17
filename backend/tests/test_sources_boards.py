from datetime import UTC, datetime

import httpx
import pytest

from sanket.sources.boards import valid_slugs
from sanket.sources.greenhouse import GreenhouseSource, fetch_board
from sanket.sources.http import BudgetExceededError
from sanket.sources.lever import LeverSource, fetch_company
from tests.source_helpers import load_json, make_fetcher

PUBLISHED_EPOCH = 1_762_761_600


class SpendLimit:
    """A request budget that allows a fixed number of requests."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed

    def spend(self, source: str) -> None:
        if self.allowed <= 0:
            raise BudgetExceededError(f"{source}: budget used up")
        self.allowed -= 1


def board_slug(path: str) -> str:
    """The board slug in /v1/boards/<slug>/jobs (Greenhouse) or /v0/postings/<slug> (Lever)."""
    parts = path.rstrip("/").split("/")
    return parts[-2] if parts[-1] == "jobs" else parts[-1]


def board_handler(boards: dict[str, object], seen: list[httpx.Request] | None = None):
    """Serve the JSON registered for each board slug, and 404 for unknown ones."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        slug = board_slug(request.url.path)
        if slug not in boards:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=boards[slug])

    return handle


def test_valid_slugs_keeps_only_url_safe_slugs() -> None:
    assert valid_slugs("test", ["acme", "Acme_2", "ac/me", "..", "-bad", "", "a b"]) == [
        "acme",
        "Acme_2",
    ]


def test_greenhouse_maps_fields_and_decodes_the_content_once() -> None:
    http = make_fetcher(board_handler({"acme": load_json("greenhouse.json")}))

    postings = {p.source_id: p for p in fetch_board(http, "acme")}

    posting = postings["acme:4001"]
    assert posting.source == "greenhouse"
    assert posting.title == "Platform Engineer"
    assert posting.company == "Acme Inc"
    assert posting.location == "Remote - EU"
    assert posting.url == "https://boards.greenhouse.io/acme/jobs/4001"
    assert posting.description == "<p>Build &amp; run the platform.</p>"
    assert posting.published_at == datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
    assert posting.raw["id"] == 4001


def test_greenhouse_leaves_optional_fields_empty() -> None:
    http = make_fetcher(board_handler({"acme": load_json("greenhouse.json")}))

    posting = {p.source_id: p for p in fetch_board(http, "acme")}["acme:4002"]

    assert posting.company is None
    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None
    assert posting.published_at is None


def test_greenhouse_skips_bad_items_instead_of_failing_the_board() -> None:
    http = make_fetcher(board_handler({"acme": load_json("greenhouse.json")}))

    postings = fetch_board(http, "acme")

    # 4003 has no url and 4004 has an unparseable date.
    assert [p.source_id for p in postings] == ["acme:4001", "acme:4002"]


def test_greenhouse_asks_for_full_content() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({"acme": {"jobs": []}}, seen))

    fetch_board(http, "acme")

    assert seen[0].url.params["content"] == "true"
    assert seen[0].url.path == "/v1/boards/acme/jobs"


@pytest.mark.parametrize("payload", [{}, {"jobs": None}, {"jobs": []}])
def test_greenhouse_board_without_jobs_gives_no_postings(payload: dict) -> None:
    http = make_fetcher(board_handler({"acme": payload}))

    assert fetch_board(http, "acme") == []


def test_greenhouse_failing_board_is_counted_and_the_rest_continue() -> None:
    http = make_fetcher(board_handler({"acme": load_json("greenhouse.json")}))

    result = GreenhouseSource(["gone", "acme"]).fetch(http)

    assert len(result.postings) == 2
    assert result.failed == 1
    assert result.skipped == 0


def test_greenhouse_raises_when_every_board_fails() -> None:
    http = make_fetcher(board_handler({}))

    with pytest.raises(RuntimeError, match="all 2 boards failed"):
        GreenhouseSource(["gone", "missing"]).fetch(http)


def test_greenhouse_ignores_invalid_slugs_without_requesting_them() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({"acme": {"jobs": []}}, seen))

    source = GreenhouseSource(["ac/me", "..", "acme"])
    source.fetch(http)

    assert source.boards == ["acme"]
    assert len(seen) == 1


def test_greenhouse_with_no_boards_makes_no_requests() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({}, seen))

    result = GreenhouseSource([]).fetch(http)

    assert result.postings == []
    assert seen == []


def test_greenhouse_reports_boards_skipped_when_the_budget_runs_out() -> None:
    boards = {"acme": load_json("greenhouse.json"), "other": {"jobs": []}}
    http = make_fetcher(board_handler(boards), budget=SpendLimit(1))

    result = GreenhouseSource(["acme", "other"]).fetch(http)

    assert len(result.postings) == 2
    assert result.skipped == 1


def test_greenhouse_budget_exhausted_before_the_first_board_raises() -> None:
    http = make_fetcher(board_handler({"acme": {"jobs": []}}), budget=SpendLimit(0))

    with pytest.raises(BudgetExceededError):
        GreenhouseSource(["acme"]).fetch(http)


def test_lever_maps_fields_and_builds_the_description_from_its_sections() -> None:
    http = make_fetcher(board_handler({"acme": load_json("lever.json")}))

    posting = {p.source_id: p for p in fetch_company(http, "acme")}["acme:aaaa-1111"]

    assert posting.source == "lever"
    assert posting.title == "Staff Engineer"
    assert posting.company == "acme"
    assert posting.location == "Remote - US"
    assert posting.url == "https://jobs.lever.co/acme/aaaa-1111"
    assert posting.description == (
        "<div>Intro paragraph</div>\n"
        "<h3>Requirements</h3><ul><li>Python</li><li>SQL</li></ul>\n"
        "<div>Perks and benefits</div>"
    )
    assert posting.salary_text is not None
    assert posting.salary_text.startswith("100000-150000 USD")
    assert posting.published_at == datetime.fromtimestamp(PUBLISHED_EPOCH, tz=UTC)


def test_lever_leaves_optional_fields_empty() -> None:
    http = make_fetcher(board_handler({"acme": load_json("lever.json")}))

    posting = {p.source_id: p for p in fetch_company(http, "acme")}["acme:bbbb-2222"]

    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None
    assert posting.published_at is None


def test_lever_tolerates_null_nested_objects() -> None:
    http = make_fetcher(board_handler({"acme": load_json("lever.json")}))

    posting = {p.source_id: p for p in fetch_company(http, "acme")}["acme:dddd-4444"]

    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None


def test_lever_skips_postings_without_a_url() -> None:
    http = make_fetcher(board_handler({"acme": load_json("lever.json")}))

    ids = [p.source_id for p in fetch_company(http, "acme")]

    assert ids == ["acme:aaaa-1111", "acme:bbbb-2222", "acme:dddd-4444"]


def test_lever_requests_json_mode() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({"acme": []}, seen))

    fetch_company(http, "acme")

    assert seen[0].url.params["mode"] == "json"
    assert seen[0].url.path == "/v0/postings/acme"


def test_lever_failing_company_is_counted_and_the_rest_continue() -> None:
    http = make_fetcher(board_handler({"acme": load_json("lever.json")}))

    result = LeverSource(["gone", "acme"]).fetch(http)

    assert len(result.postings) == 3
    assert result.failed == 1


def test_lever_raises_when_every_company_fails() -> None:
    http = make_fetcher(board_handler({}))

    with pytest.raises(RuntimeError, match="all 1 boards failed"):
        LeverSource(["gone"]).fetch(http)
