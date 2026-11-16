"""Tests for the USAJOBS adapter.

IMPORTANT: `fixtures/usajobs.json` is NOT a recording. No API key was available, so it was
written by hand from the response shape documented at developer.usajobs.gov. All values are
invented. Which fields the live API actually fills in, and in what form (for example whether
`MajorDuties` is a list or a string, or how salary strings look), is unverified.
"""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from sanket.ingest import STATUS_OK, STATUS_SKIPPED, run_source
from sanket.sources.base import SourceNotConfiguredError
from sanket.sources.http import BudgetExceededError
from sanket.sources.usajobs import MAX_PAGES, MAX_REQUESTS_PER_DAY, PAGE_SIZE, UsaJobsSource
from sanket.storage import SaveResult
from tests.source_helpers import json_handler, load_json, make_fetcher
from tests.test_sources_boards import SpendLimit

KEY = "key-not-a-real-secret"
EMAIL = "owner@example.com"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def source() -> UsaJobsSource:
    return UsaJobsSource(SecretStr(KEY), EMAIL)


def fetch_fixture():
    result = source().fetch(make_fetcher(json_handler(load_json("usajobs.json"))))
    return result, {posting.source_id: posting for posting in result.postings}


def test_usajobs_maps_the_documented_fields() -> None:
    _, postings = fetch_fixture()

    posting = postings["900000001"]
    assert posting.source == "usajobs"
    assert posting.url == "https://www.usajobs.gov/GetJob/ViewDetails/900000001"
    assert posting.title == "IT Specialist (APPSW)"
    assert posting.company == "Example Agency"
    assert posting.location == "Washington, District of Columbia"
    assert posting.salary_text == "92108-119746 Per Year"
    assert posting.published_at == datetime(2026, 11, 15, tzinfo=UTC)
    assert posting.deadline == date(2026, 12, 1)
    assert posting.raw["MatchedObjectId"] == "900000001"


def test_usajobs_joins_the_description_sections_and_lists() -> None:
    _, postings = fetch_fixture()

    assert postings["900000001"].description == (
        "Develops and maintains software.\n\n"
        "Write code.\nReview code.\n\n"
        "One year of specialised experience.\n\n"
        "You must be a U.S. citizen."
    )


def test_usajobs_accepts_a_duty_given_as_one_string() -> None:
    _, postings = fetch_fixture()

    assert postings["900000004"].description == "Single string duty."


def test_usajobs_leaves_optional_fields_empty() -> None:
    _, postings = fetch_fixture()

    posting = postings["900000002"]
    assert posting.company is None
    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None
    assert posting.published_at is None
    assert posting.deadline is None


def test_usajobs_keeps_the_job_when_the_pay_range_is_unreadable() -> None:
    _, postings = fetch_fixture()

    assert postings["900000004"].salary_text == "Per Hour"
    assert postings["900000004"].deadline is None


def test_usajobs_skips_items_without_a_uri_instead_of_failing_the_run() -> None:
    result, postings = fetch_fixture()

    # 900000003 has no PositionURI.
    assert list(postings) == ["900000001", "900000002", "900000004"]
    assert result.failed == 1


def test_usajobs_sends_the_documented_headers_and_parameters() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"SearchResult": {"SearchResultItems": []}})

    source().fetch(make_fetcher(handle))

    request = seen[0]
    assert request.url.host == "data.usajobs.gov"
    assert request.url.path == "/api/Search"
    assert request.headers["Host"] == "data.usajobs.gov"
    assert request.headers["User-Agent"] == EMAIL
    assert request.headers["Authorization-Key"] == KEY
    params = request.url.params
    assert params["DatePosted"] == "2"
    assert params["ResultsPerPage"] == "500"
    assert params["Page"] == "1"
    assert params["WhoMayApply"] == "public"
    assert params["Fields"] == "Full"


@pytest.mark.parametrize(
    ("key", "email"),
    [(None, None), (SecretStr(KEY), None), (None, EMAIL), (SecretStr(KEY), "  ")],
)
def test_usajobs_without_a_key_or_email_makes_no_request(key, email) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(SourceNotConfiguredError):
        UsaJobsSource(key, email).fetch(make_fetcher(handle))

    assert seen == []


def test_the_not_configured_message_never_contains_the_credentials() -> None:
    with pytest.raises(SourceNotConfiguredError) as error:
        UsaJobsSource(None, EMAIL).fetch(make_fetcher(json_handler({})))

    assert EMAIL not in str(error.value)
    assert "USAJOBS_API_KEY" in str(error.value)


def test_run_source_reports_usajobs_skipped_when_it_is_not_configured() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    saved: list[dict] = []

    def save(rows: list[dict]) -> SaveResult:
        saved.extend(rows)
        return SaveResult()

    summary = run_source(UsaJobsSource(None, None), make_fetcher(handle), None, NOW, save=save)

    assert summary.status == STATUS_SKIPPED
    assert summary.skipped == 1
    assert seen == []
    assert saved == []


def test_run_source_saves_usajobs_postings_and_counts_the_malformed_ones() -> None:
    saved: list[dict] = []

    def save(rows: list[dict]) -> SaveResult:
        saved.extend(rows)
        return SaveResult(new=len(rows))

    http = make_fetcher(json_handler(load_json("usajobs.json")))
    summary = run_source(source(), http, None, NOW, save=save)

    assert summary.status == STATUS_OK
    assert {row["source"] for row in saved} == {"usajobs"}
    assert (summary.fetched, summary.failed) == (3, 1)


def test_usajobs_http_errors_do_not_leak_the_credentials() -> None:
    http = make_fetcher(lambda request: httpx.Response(401, json={}))

    with pytest.raises(httpx.HTTPStatusError) as error:
        source().fetch(http)

    assert KEY not in str(error.value)
    assert EMAIL not in str(error.value)


def job(job_id: int) -> dict:
    return {
        "MatchedObjectId": str(job_id),
        "MatchedObjectDescriptor": {
            "PositionTitle": f"Job {job_id}",
            "PositionURI": f"https://www.usajobs.gov/GetJob/ViewDetails/{job_id}",
        },
    }


def paged_handler(total: int, seen: list[httpx.Request] | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        first = (int(request.url.params["Page"]) - 1) * PAGE_SIZE
        ids = range(first, min(first + PAGE_SIZE, total))
        body = {
            "SearchResult": {
                "SearchResultCountAll": total,
                "SearchResultItems": [job(i) for i in ids],
            }
        }
        return httpx.Response(200, json=body)

    return handle


def test_usajobs_reads_pages_until_the_total_is_reached() -> None:
    seen: list[httpx.Request] = []

    result = source().fetch(make_fetcher(paged_handler(1200, seen)))

    assert [r.url.params["Page"] for r in seen] == ["1", "2", "3"]
    assert len(result.postings) == 1200
    assert result.skipped == 0


def test_usajobs_stops_when_the_total_fits_in_one_page() -> None:
    seen: list[httpx.Request] = []

    source().fetch(make_fetcher(paged_handler(PAGE_SIZE, seen)))

    assert len(seen) == 1


def test_usajobs_page_cap_bounds_the_run() -> None:
    seen: list[httpx.Request] = []

    result = source().fetch(make_fetcher(paged_handler(PAGE_SIZE * 50, seen)))

    assert len(seen) == MAX_PAGES
    assert len(result.postings) == MAX_PAGES * PAGE_SIZE


def test_usajobs_stops_on_an_empty_page_even_if_the_total_is_larger() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"SearchResult": {"SearchResultCountAll": 9999, "SearchResultItems": []}}
        return httpx.Response(200, json=body)

    result = source().fetch(make_fetcher(handle))

    assert len(seen) == 1
    assert result.postings == []


def test_usajobs_budget_running_out_mid_run_keeps_the_pages_already_fetched() -> None:
    http = make_fetcher(paged_handler(PAGE_SIZE * 50), budget=SpendLimit(2))

    result = source().fetch(http)

    assert len(result.postings) == 2 * PAGE_SIZE
    assert result.skipped == 1


def test_usajobs_budget_used_up_before_the_first_page_raises() -> None:
    http = make_fetcher(paged_handler(10), budget=SpendLimit(0))

    with pytest.raises(BudgetExceededError):
        source().fetch(http)


@pytest.mark.parametrize("payload", [{}, {"SearchResult": None}, {"SearchResult": {}}])
def test_usajobs_empty_responses_give_no_postings(payload: dict) -> None:
    result = source().fetch(make_fetcher(json_handler(payload)))

    assert result.postings == []


def test_usajobs_budget_and_interval() -> None:
    assert source().max_requests_per_day == MAX_REQUESTS_PER_DAY
    assert source().min_interval == timedelta(hours=1)


def test_usajobs_raw_holds_no_credentials() -> None:
    _, postings = fetch_fixture()

    stored = json.dumps(postings["900000001"].raw)

    assert KEY not in stored
    assert EMAIL not in stored
