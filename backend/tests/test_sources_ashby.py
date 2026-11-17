"""Tests for the Ashby board adapter.

Fixture `ashby.json`: the first two jobs are recorded from the public Ashby board
(trimmed descriptions; the first one gets a recorded `compensation` object copied from the
live response). The jobs whose id starts with `hand-` were written by hand to cover
unlisted, HTML-only, no-location, no-url and bad-date items, which the live board did not
happen to contain; they are not recordings.
"""

from datetime import UTC, datetime

import httpx
import pytest

from sanket.ingest import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, run_source
from sanket.sources.ashby import AshbySource, fetch_board
from sanket.sources.http import BudgetExceededError
from sanket.storage import SaveResult
from tests.source_helpers import load_json, make_fetcher
from tests.test_sources_boards import SpendLimit

FIRST_ID = "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
SECOND_ID = "86a60834-ba64-484d-9658-afa1bc97a957"
NOW = datetime(2026, 11, 17, tzinfo=UTC)


def board_handler(boards: dict[str, object], seen: list[httpx.Request] | None = None):
    """Serve the JSON registered for each board slug, and 404 for unknown ones."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        slug = request.url.path.rstrip("/").split("/")[-1]
        if slug not in boards:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=boards[slug])

    return handle


def fixture_postings() -> dict:
    http = make_fetcher(board_handler({"acme": load_json("ashby.json")}))
    return {posting.source_id: posting for posting in fetch_board(http, "acme")}


def test_ashby_maps_fields_from_a_recorded_job() -> None:
    posting = fixture_postings()[FIRST_ID]

    assert posting.source == "ashby"
    assert posting.title == "Engineering Manager - EU"
    assert posting.company == "acme"
    assert posting.location == "Remote - European Union"
    assert posting.url == f"https://jobs.ashbyhq.com/Ashby/{FIRST_ID}"
    assert posting.description is not None
    assert posting.description.startswith("Hi")
    assert "<p" not in posting.description
    assert posting.published_at == datetime(2024, 3, 4, 14, 29, 8, 532000, tzinfo=UTC)
    assert posting.raw["id"] == FIRST_ID


def test_ashby_uses_the_employers_compensation_summary() -> None:
    posting = fixture_postings()[FIRST_ID]

    assert posting.salary_text is not None
    assert "150K" in posting.salary_text


def test_ashby_marks_a_remote_job_whose_location_does_not_say_so() -> None:
    assert fixture_postings()[SECOND_ID].location == "France (Remote)"


def test_ashby_remote_job_without_a_location_is_just_remote() -> None:
    posting = fixture_postings()["hand-0005-no-location"]

    assert posting.location == "Remote"
    assert posting.published_at is None


def test_ashby_falls_back_to_the_html_description_and_respects_hidden_pay() -> None:
    posting = fixture_postings()["hand-0004-html-only"]

    assert posting.title == "Support Engineer"
    assert posting.description == "<p>Help &amp; support customers.</p>"
    assert posting.location == "Berlin"
    # The employer set shouldDisplayCompensationOnJobPostings to false.
    assert posting.salary_text is None


def test_ashby_uses_the_scrapeable_summary_when_the_tier_summary_is_empty() -> None:
    assert fixture_postings()["hand-0005-no-location"].salary_text == "$90K - $120K"


def test_ashby_leaves_pay_empty_when_there_is_no_compensation() -> None:
    assert fixture_postings()[SECOND_ID].salary_text is None


def test_ashby_drops_unlisted_jobs() -> None:
    assert "hand-0003-unlisted" not in fixture_postings()


def test_ashby_skips_bad_items_instead_of_failing_the_board() -> None:
    ids = list(fixture_postings())

    # hand-0006 has no jobUrl and hand-0007 has an unparseable date.
    assert ids == [FIRST_ID, SECOND_ID, "hand-0004-html-only", "hand-0005-no-location"]


def test_ashby_skips_items_that_are_not_objects() -> None:
    payload = {"jobs": ["oops", None, {"id": "x", "title": "T", "jobUrl": "https://e.com/x"}]}
    http = make_fetcher(board_handler({"acme": payload}))

    assert [p.source_id for p in fetch_board(http, "acme")] == ["x"]


def test_ashby_asks_for_compensation_on_the_documented_path() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({"acme": {"jobs": []}}, seen))

    fetch_board(http, "acme")

    assert seen[0].url.path == "/posting-api/job-board/acme"
    assert seen[0].url.params["includeCompensation"] == "true"


@pytest.mark.parametrize("payload", [{}, {"jobs": None}, {"jobs": []}])
def test_ashby_board_without_jobs_gives_no_postings(payload: dict) -> None:
    http = make_fetcher(board_handler({"acme": payload}))

    assert fetch_board(http, "acme") == []


def test_ashby_failing_board_is_counted_and_the_rest_continue() -> None:
    http = make_fetcher(board_handler({"acme": load_json("ashby.json")}))

    result = AshbySource(["gone", "acme"]).fetch(http)

    assert len(result.postings) == 4
    assert result.failed == 1


def test_ashby_raises_when_every_board_fails() -> None:
    http = make_fetcher(board_handler({}))

    with pytest.raises(RuntimeError, match="all 2 boards failed"):
        AshbySource(["gone", "missing"]).fetch(http)


def test_ashby_ignores_invalid_slugs_without_requesting_them() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({"acme": {"jobs": []}}, seen))

    source = AshbySource(["ac/me", "..", "acme"])
    source.fetch(http)

    assert source.boards == ["acme"]
    assert len(seen) == 1


def test_ashby_with_no_boards_makes_no_requests() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(board_handler({}, seen))

    result = AshbySource([]).fetch(http)

    assert result.postings == []
    assert seen == []


def test_ashby_reports_boards_skipped_when_the_budget_runs_out() -> None:
    boards = {"acme": load_json("ashby.json"), "other": {"jobs": []}}
    http = make_fetcher(board_handler(boards), budget=SpendLimit(1))

    result = AshbySource(["acme", "other"]).fetch(http)

    assert len(result.postings) == 4
    assert result.skipped == 1


def test_ashby_budget_exhausted_before_the_first_board_raises() -> None:
    http = make_fetcher(board_handler({"acme": {"jobs": []}}), budget=SpendLimit(0))

    with pytest.raises(BudgetExceededError):
        AshbySource(["acme"]).fetch(http)


def run_with_stub_save(source: AshbySource, boards: dict[str, object]):
    saved: list[dict] = []

    def save(rows: list[dict]) -> SaveResult:
        saved.extend(rows)
        return SaveResult(new=len(rows))

    summary = run_source(source, make_fetcher(board_handler(boards)), None, NOW, save=save)
    return summary, saved


def test_run_source_saves_ashby_postings_and_counts_the_bad_items() -> None:
    summary, saved = run_with_stub_save(AshbySource(["acme"]), {"acme": load_json("ashby.json")})

    assert summary.status == STATUS_OK
    assert [row["source"] for row in saved] == ["ashby"] * 4
    assert (summary.fetched, summary.new) == (4, 4)


def test_run_source_reports_a_failed_ashby_run() -> None:
    summary, _ = run_with_stub_save(AshbySource(["gone"]), {})

    assert summary.status == STATUS_FAILED


def test_run_source_reports_ashby_skipped_when_the_budget_is_used_up() -> None:
    http = make_fetcher(board_handler({"acme": {"jobs": []}}), budget=SpendLimit(0))

    summary = run_source(AshbySource(["acme"]), http, None, NOW, save=lambda rows: SaveResult())

    assert summary.status == STATUS_SKIPPED
