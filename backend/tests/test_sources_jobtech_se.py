"""Tests for the JobTech Sweden (JobSearch API) adapter.

Fixture `jobtech_se.json`: the first two ads are recorded from the live API (descriptions
trimmed; the named contact on the second ad was replaced by a synthetic one before
committing, so no real person is stored here). The ads whose id starts with `hand-` were
written by hand: a removed ad, an ad full of contact data, an ad without a URL and an ad
without an employer. They are not recordings.
"""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from sanket.ingest import STATUS_OK, STATUS_SKIPPED, run_source
from sanket.sources.http import BudgetExceededError
from sanket.sources.jobtech_se import PAGE_SIZE, JobTechSource, redact_personal_data
from sanket.storage import SaveResult
from tests.source_helpers import json_handler, load_json, make_fetcher
from tests.test_sources_boards import SpendLimit

CLOCK_NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
FIRST_ID = "31629347"
SECOND_ID = "31702286"


def source(**kwargs) -> JobTechSource:
    return JobTechSource(clock=lambda: CLOCK_NOW, **kwargs)


def fetch_fixture(**kwargs):
    http = make_fetcher(json_handler(load_json("jobtech_se.json")))
    result = source(**kwargs).fetch(http)
    return result, {posting.source_id: posting for posting in result.postings}


def test_jobtech_maps_fields_from_a_recorded_ad() -> None:
    _, postings = fetch_fixture()

    posting = postings[FIRST_ID]
    assert posting.source == "jobtech_se"
    assert posting.url == "https://arbetsformedlingen.se/platsbanken/annonser/31629347"
    assert posting.title == "Developer"
    assert posting.company == "Rasulson Consulting AB"
    assert posting.location == "Stockholm, Stockholms län, Sverige"
    assert posting.description is not None
    assert posting.description.startswith("Senior Robotics Engineer")
    assert posting.salary_text == "Fast månads- vecko- eller timlön"
    assert posting.deadline == date(2026, 11, 27)
    assert posting.raw["id"] == FIRST_ID


def test_jobtech_attaches_swedish_summer_time_to_naive_timestamps() -> None:
    _, postings = fetch_fixture()

    published = postings[FIRST_ID].published_at
    # 2026-10-22 is before the clocks go back, so Stockholm is UTC+2.
    assert published == datetime(2026, 10, 21, 22, 0, tzinfo=UTC)
    assert published is not None
    assert published.utcoffset() == timedelta(hours=2)


def test_jobtech_attaches_swedish_winter_time_to_naive_timestamps() -> None:
    _, postings = fetch_fixture()

    published = postings[SECOND_ID].published_at
    assert published == datetime(2026, 11, 9, 8, 13, 31, tzinfo=UTC)
    assert published is not None
    assert published.utcoffset() == timedelta(hours=1)


def test_jobtech_prefers_the_salary_description_and_allows_no_deadline() -> None:
    _, postings = fetch_fixture()

    posting = postings["hand-contacts"]
    assert posting.salary_text == "35 000 - 45 000 kr per månad"
    assert posting.deadline is None
    assert posting.published_at == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def test_jobtech_leaves_company_and_location_empty_without_an_employer_or_address() -> None:
    _, postings = fetch_fixture()

    posting = postings["hand-no-employer"]
    assert posting.company is None
    assert posting.location is None


def test_jobtech_drops_removed_ads_without_counting_them_as_failures() -> None:
    result, postings = fetch_fixture()

    assert "hand-removed" not in postings
    # Only the ad without a URL is malformed.
    assert result.failed == 1
    assert "hand-no-url" not in postings
    assert len(postings) == 4


def test_jobtech_strips_contact_data_from_raw() -> None:
    _, postings = fetch_fixture()

    stored = json.dumps(postings["hand-contacts"].raw)

    for personal in ("Test Person", "person@example.com", "+46000000002", "+46000000001"):
        assert personal not in stored
    assert "hr@example.com" not in stored
    assert "apply@example.com" not in stored
    assert "Call Test Person" not in stored
    assert "application_contacts" not in postings["hand-contacts"].raw


def test_jobtech_strips_the_contact_on_a_recorded_ad_too() -> None:
    _, postings = fetch_fixture()

    stored = json.dumps(postings[SECOND_ID].raw)

    assert "Test Contact" not in stored
    assert "+46000000000" not in stored
    assert "redacted@example.com" not in stored


def test_jobtech_keeps_the_apply_link_and_employer_name_in_raw() -> None:
    _, postings = fetch_fixture()

    raw = postings["hand-contacts"].raw

    assert raw["application_details"] == {"url": "https://example.com/apply", "via_af": False}
    assert raw["employer"]["name"] == "Example AB"
    assert raw["headline"] == "Hand written hand-contacts"


def test_redaction_does_not_change_the_ad_it_is_given() -> None:
    ad = load_json("jobtech_se.json")["hits"][1]
    before = json.dumps(ad, sort_keys=True)

    redacted = redact_personal_data(ad)

    assert json.dumps(ad, sort_keys=True) == before
    assert "application_contacts" not in redacted


def test_jobtech_asks_for_the_newest_ads_since_the_lookback_in_swedish_time() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"total": {"value": 0}, "hits": []})

    source(lookback=timedelta(days=2)).fetch(make_fetcher(handle))

    params = seen[0].url.params
    assert seen[0].url.path == "/search"
    assert params["limit"] == "100"
    assert params["offset"] == "0"
    assert params["sort"] == "pubdate-desc"
    # 2026-11-15 12:00 UTC is 13:00 in Stockholm.
    assert params["published-after"] == "2026-11-15T13:00:00"
    assert "q" not in params


def test_jobtech_sends_the_query_only_when_configured() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"hits": []})

    source(query="  python  ").fetch(make_fetcher(handle))
    source(query="   ").fetch(make_fetcher(handle))

    assert seen[0].url.params["q"] == "python"
    assert "q" not in seen[1].url.params


def minimal_ad(ad_id: int) -> dict:
    return {
        "id": str(ad_id),
        "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}",
        "headline": f"Job {ad_id}",
        "publication_date": "2026-11-10T09:00:00",
    }


def paged_handler(total: int, seen: list[httpx.Request] | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        offset = int(request.url.params["offset"])
        ids = range(offset, min(offset + PAGE_SIZE, total))
        return httpx.Response(
            200, json={"total": {"value": total}, "hits": [minimal_ad(i) for i in ids]}
        )

    return handle


def test_jobtech_reads_pages_until_the_total_is_reached() -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    result = source(max_pages=5).fetch(make_fetcher(paged_handler(250, seen), sleeps=sleeps))

    assert [r.url.params["offset"] for r in seen] == ["0", "100", "200"]
    assert len(result.postings) == 250
    assert result.skipped == 0
    # One pause between pages, none before the first.
    assert len(sleeps) == 2


def test_jobtech_stops_after_the_last_full_page_when_the_total_is_reached() -> None:
    seen: list[httpx.Request] = []

    result = source(max_pages=5).fetch(make_fetcher(paged_handler(200, seen)))

    assert len(seen) == 2
    assert len(result.postings) == 200


def test_jobtech_page_cap_bounds_the_run() -> None:
    seen: list[httpx.Request] = []

    result = source(max_pages=2).fetch(make_fetcher(paged_handler(5000, seen)))

    assert len(seen) == 2
    assert len(result.postings) == 200


def test_jobtech_budget_running_out_mid_run_keeps_the_pages_already_fetched() -> None:
    http = make_fetcher(paged_handler(5000), budget=SpendLimit(2))

    result = source(max_pages=5).fetch(http)

    assert len(result.postings) == 200
    assert result.skipped == 1


def test_jobtech_budget_used_up_before_the_first_page_raises() -> None:
    http = make_fetcher(paged_handler(5000), budget=SpendLimit(0))

    with pytest.raises(BudgetExceededError):
        source().fetch(http)


@pytest.mark.parametrize("payload", [{}, {"hits": None}, {"total": None, "hits": []}])
def test_jobtech_empty_responses_give_no_postings(payload: dict) -> None:
    result = source().fetch(make_fetcher(json_handler(payload)))

    assert result.postings == []


def test_jobtech_budget_and_interval_follow_the_page_cap() -> None:
    assert source(max_pages=5).max_requests_per_day == 40
    assert source(max_pages=10).max_requests_per_day == 80
    assert source().min_interval == timedelta(hours=1)


def test_run_source_saves_jobtech_ads_and_counts_the_malformed_one() -> None:
    saved: list[dict] = []

    def save(rows: list[dict]) -> SaveResult:
        saved.extend(rows)
        return SaveResult(new=len(rows))

    http = make_fetcher(json_handler(load_json("jobtech_se.json")))
    summary = run_source(source(), http, None, CLOCK_NOW, save=save)

    assert summary.status == STATUS_OK
    assert (summary.fetched, summary.failed, summary.new) == (4, 1, 4)
    assert {row["source"] for row in saved} == {"jobtech_se"}
    assert all("application_contacts" not in row["raw"] for row in saved)


def test_run_source_skips_jobtech_when_it_ran_within_the_minimum_interval() -> None:
    http = make_fetcher(json_handler({"hits": []}))

    summary = run_source(
        source(), http, CLOCK_NOW - timedelta(minutes=10), CLOCK_NOW, save=lambda rows: SaveResult()
    )

    assert summary.status == STATUS_SKIPPED


def test_parse_local_datetime_keeps_an_offset_that_is_already_present() -> None:
    from zoneinfo import ZoneInfo

    from sanket.sources.fields import parse_local_datetime

    stockholm = ZoneInfo("Europe/Stockholm")

    assert parse_local_datetime("2026-11-09T09:00:00Z", stockholm) == datetime(
        2026, 11, 9, 9, 0, tzinfo=UTC
    )
    assert parse_local_datetime(None, stockholm) is None
    assert parse_local_datetime("", stockholm) is None
