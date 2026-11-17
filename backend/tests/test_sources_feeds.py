import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from sanket.ingest import STATUS_OK, run_source
from sanket.sources.himalayas import HimalayasSource
from sanket.sources.http import BudgetExceededError
from sanket.sources.jobicy import JobicySource, fetch_jobicy_jobs
from sanket.sources.remoteok import RemoteOkSource
from sanket.sources.remotive import RemotiveSource
from sanket.sources.weworkremotely import WeWorkRemotelySource
from sanket.storage import SaveResult
from tests.source_helpers import json_handler, load_bytes, load_json, make_fetcher

PUBLISHED_EPOCH = 1_762_761_600
PUBLISHED = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def by_id(result) -> dict:
    return {posting.source_id: posting for posting in result.postings}


class StopAfter:
    """A request budget that allows a fixed number of requests."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed

    def spend(self, source: str) -> None:
        if self.allowed <= 0:
            raise BudgetExceededError(f"{source}: budget used up")
        self.allowed -= 1


def paged_handler(fixture: str, cursor_value: str, seen: list[httpx.Request] | None = None):
    pages = load_json(fixture)

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        page = "second_page" if request.url.params.get("cursor") == cursor_value else "first_page"
        return httpx.Response(200, json=pages[page])

    return handle


# --- We Work Remotely -------------------------------------------------------------------


def fetch_wwr(content: bytes):
    http = make_fetcher(lambda request: httpx.Response(200, content=content))
    return WeWorkRemotelySource().fetch(http)


def test_wwr_maps_the_feed_item_fields() -> None:
    result = fetch_wwr(load_bytes("weworkremotely.xml"))

    posting = by_id(result)["https://weworkremotely.com/remote-jobs/acme-senior-python"]
    assert posting.source == "weworkremotely"
    assert posting.company == "Acme Corp"
    assert posting.title == "Senior Python Developer"
    assert posting.location == "Anywhere in the World, Germany"
    assert posting.url == posting.source_id
    assert posting.description == "<p>Build <b>APIs</b> &amp; services.</p>"
    assert posting.published_at == PUBLISHED
    assert posting.raw["guid"] == posting.source_id


def test_wwr_skips_namespaced_child_elements_in_raw() -> None:
    result = fetch_wwr(load_bytes("weworkremotely.xml"))

    raw = by_id(result)["https://weworkremotely.com/remote-jobs/acme-senior-python"].raw

    assert not any("}" in key for key in raw)
    assert "content" not in raw


def test_wwr_title_without_a_company_separator_keeps_the_whole_title() -> None:
    result = fetch_wwr(load_bytes("weworkremotely.xml"))

    posting = by_id(result)["https://weworkremotely.com/remote-jobs/no-company"]

    assert posting.company is None
    assert posting.title == "A title with no company separator"
    assert posting.location is None
    assert posting.description is None
    assert posting.published_at is None


def test_wwr_decodes_entities_and_gmt_dates() -> None:
    result = fetch_wwr(load_bytes("weworkremotely.xml"))

    posting = by_id(result)["https://weworkremotely.com/remote-jobs/tom-jerry"]

    assert posting.company == "Tom & Jerry Ltd"
    assert posting.title == "Data Engineer"
    assert posting.published_at == datetime(2026, 11, 11, 12, 30, tzinfo=UTC)


def test_wwr_skips_bad_items_instead_of_failing_the_feed() -> None:
    result = fetch_wwr(load_bytes("weworkremotely.xml"))

    assert len(result.postings) == 3
    assert result.failed == 2


def test_wwr_empty_channel_gives_no_postings() -> None:
    xml = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'

    result = fetch_wwr(xml)

    assert result.postings == []
    assert result.failed == 0


def test_wwr_unparseable_feed_fails_the_source() -> None:
    with pytest.raises(ET.ParseError):
        fetch_wwr(b"<rss><channel><item>")


# --- Himalayas --------------------------------------------------------------------------


def test_himalayas_follows_the_cursor_and_skips_items_without_a_guid() -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    http = make_fetcher(paged_handler("himalayas.json", "page-2", seen), sleeps=sleeps)

    result = HimalayasSource().fetch(http)

    assert len(result.postings) == 3
    assert result.failed == 1
    assert result.skipped == 0
    assert [r.url.params.get("cursor") for r in seen] == [None, "page-2"]
    assert seen[0].url.params["limit"] == "20"
    assert sleeps == [1.0]


def test_himalayas_maps_fields() -> None:
    http = make_fetcher(paged_handler("himalayas.json", "page-2"))

    result = HimalayasSource().fetch(http)

    posting = by_id(result)["https://himalayas.app/companies/acme/jobs/backend-engineer"]
    assert posting.source == "himalayas"
    assert posting.title == "Backend Engineer"
    assert posting.company == "Acme & Sons"
    assert posting.url == "https://himalayas.app/apply/backend-engineer"
    assert posting.location == "Germany, France"
    assert posting.description == "<p>Build APIs.</p>"
    assert posting.salary_text == "60000-80000 EUR per year"
    assert posting.published_at == datetime.fromtimestamp(PUBLISHED_EPOCH, tz=UTC)


def test_himalayas_fills_in_missing_optional_fields() -> None:
    http = make_fetcher(paged_handler("himalayas.json", "page-2"))

    result = HimalayasSource().fetch(http)

    designer = by_id(result)["https://himalayas.app/companies/studio/jobs/designer"]
    assert designer.title == "Designer & Illustrator"
    assert designer.url == designer.source_id
    assert designer.location == "Worldwide"
    assert designer.salary_text is None
    assert designer.published_at is None
    analyst = by_id(result)["https://himalayas.app/companies/beta/jobs/analyst"]
    assert analyst.location == "Worldwide"
    assert analyst.company is None


def test_himalayas_sends_the_api_key_only_when_configured() -> None:
    seen: list[httpx.Request] = []
    handler = paged_handler("himalayas.json", "page-2", seen)

    HimalayasSource(SecretStr("secret-key")).fetch(make_fetcher(handler))
    keyed = list(seen)
    seen.clear()
    HimalayasSource().fetch(make_fetcher(handler))

    assert all(r.headers["authorization"] == "Bearer secret-key" for r in keyed)
    assert all("authorization" not in r.headers for r in seen)


def test_himalayas_budget_running_out_mid_run_keeps_the_pages_already_fetched() -> None:
    http = make_fetcher(paged_handler("himalayas.json", "page-2"), budget=StopAfter(1))

    result = HimalayasSource().fetch(http)

    assert len(result.postings) == 2
    assert result.skipped == 1


def test_himalayas_budget_used_up_before_the_first_page_raises() -> None:
    http = make_fetcher(paged_handler("himalayas.json", "page-2"), budget=StopAfter(0))

    with pytest.raises(BudgetExceededError):
        HimalayasSource().fetch(http)


@pytest.mark.parametrize("payload", [{}, {"jobs": None}, {"jobs": [], "nextCursor": None}])
def test_himalayas_empty_responses_give_no_postings(payload: dict) -> None:
    result = HimalayasSource().fetch(make_fetcher(json_handler(payload)))

    assert result.postings == []
    assert result.failed == 0


# --- Jobicy -----------------------------------------------------------------------------


def test_jobicy_follows_the_cursor_and_skips_items_without_a_url() -> None:
    seen: list[httpx.Request] = []
    http = make_fetcher(paged_handler("jobicy.json", "cursor-2", seen))

    result = JobicySource().fetch(http)

    assert sorted(by_id(result)) == ["101", "102", "104"]
    assert result.failed == 1
    assert [r.url.params.get("cursor") for r in seen] == [None, "cursor-2"]
    assert seen[0].url.params["count"] == "100"


def test_jobicy_maps_fields() -> None:
    http = make_fetcher(paged_handler("jobicy.json", "cursor-2"))

    posting = by_id(JobicySource().fetch(http))["101"]

    assert posting.source == "jobicy"
    assert posting.title == "Backend & API Developer"
    assert posting.company == "Foo Labs"
    assert posting.location == "Anywhere"
    assert posting.url == "https://jobicy.com/jobs/101-backend-api-developer"
    assert posting.description == "<p>Design REST APIs.</p>"
    assert posting.salary_text == "70000-90000 USD per year"
    assert posting.published_at == PUBLISHED


def test_jobicy_leaves_optional_fields_empty() -> None:
    http = make_fetcher(paged_handler("jobicy.json", "cursor-2"))

    result = by_id(JobicySource().fetch(http))

    minimal = result["102"]
    assert minimal.company is None
    assert minimal.location is None
    assert minimal.description is None
    assert minimal.salary_text is None
    assert minimal.published_at is None
    assert result["104"].location is None


def test_jobicy_converts_offsets_to_aware_datetimes() -> None:
    http = make_fetcher(paged_handler("jobicy.json", "cursor-2"))

    posting = by_id(JobicySource().fetch(http))["104"]

    assert posting.published_at == datetime(2026, 11, 9, 6, 30, tzinfo=UTC)


def test_jobicy_stops_when_there_is_no_next_cursor() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jobs": [], "hasMore": True})

    fetch_jobicy_jobs(make_fetcher(handler))

    assert len(seen) == 1


def test_jobicy_page_cap_bounds_the_run() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jobs": [], "hasMore": True, "nextCursor": "again"})

    fetch_jobicy_jobs(make_fetcher(handler), max_pages=3)

    assert len(seen) == 3


def test_jobicy_budget_running_out_mid_run_keeps_the_pages_already_fetched() -> None:
    http = make_fetcher(paged_handler("jobicy.json", "cursor-2"), budget=StopAfter(1))

    result = JobicySource().fetch(http)

    assert sorted(by_id(result)) == ["101", "102"]
    assert result.skipped == 1


# --- Remote OK --------------------------------------------------------------------------


def fetch_remoteok():
    return RemoteOkSource().fetch(make_fetcher(json_handler(load_json("remoteok.json"))))


def test_remoteok_skips_the_legal_notice_element() -> None:
    assert sorted(by_id(fetch_remoteok())) == ["9001", "9002"]


def test_remoteok_maps_fields_and_repairs_text() -> None:
    posting = by_id(fetch_remoteok())["9001"]

    assert posting.source == "remoteok"
    assert posting.title == "Backend Dev"
    assert posting.company == "Café Co"
    assert posting.location == "Worldwide"
    assert posting.url == "https://remoteok.com/remote-jobs/9001-backend-dev"
    assert posting.salary_text == "60000-90000 USD"
    assert posting.published_at == PUBLISHED


def test_remoteok_strips_the_anti_spam_instruction_from_the_description() -> None:
    posting = by_id(fetch_remoteok())["9001"]

    assert posting.description == "<p>Work on services.</p>"
    assert "BANANA" not in posting.description


def test_remoteok_leaves_optional_fields_empty() -> None:
    posting = by_id(fetch_remoteok())["9002"]

    assert posting.company is None
    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None


# --- Remotive ---------------------------------------------------------------------------


def fetch_remotive():
    return RemotiveSource().fetch(make_fetcher(json_handler(load_json("remotive.json"))))


def test_remotive_maps_fields() -> None:
    posting = by_id(fetch_remotive())["2001"]

    assert posting.source == "remotive"
    assert posting.title == "Data Analyst"
    assert posting.company == "Beta Corp"
    assert posting.location == "USA Only"
    assert posting.description == "<p>Analyse data.</p>"
    assert posting.salary_text == "$60k-$80k"
    assert posting.url == "https://remotive.com/remote-jobs/data/data-analyst-2001"
    assert posting.published_at == PUBLISHED


def test_remotive_turns_empty_strings_and_missing_fields_into_none() -> None:
    posting = by_id(fetch_remotive())["2002"]

    assert posting.company is None
    assert posting.location is None
    assert posting.description is None
    assert posting.salary_text is None
    assert posting.published_at is None


def test_remotive_raw_keeps_the_original_job_and_the_added_aliases() -> None:
    posting = by_id(fetch_remotive())["2001"]

    assert posting.raw["company_name"] == "Beta Corp"
    assert posting.raw["company"] == "Beta Corp"
    assert posting.raw["position"] == "Data Analyst"


def test_remotive_makes_a_single_attempt_to_respect_its_daily_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503)

    source = RemotiveSource()
    http = make_fetcher(handler, max_attempts=source.max_attempts)

    with pytest.raises(httpx.HTTPStatusError):
        source.fetch(http)

    assert source.max_attempts == 1
    assert source.max_requests_per_day == 4
    assert len(seen) == 1


# --- Bad items are skipped, not fatal ---------------------------------------------------


def run_with_stub_save(source, payload):
    """Run the source the way ingest does, with the database write replaced by a stub."""
    saved: list[dict] = []

    def save(rows: list[dict]) -> SaveResult:
        saved.extend(rows)
        return SaveResult(new=len(rows))

    summary = run_source(source, make_fetcher(json_handler(payload)), None, PUBLISHED, save=save)
    return summary, saved


def remoteok_job(job_id: str, **overrides) -> dict:
    job = {
        "id": job_id,
        "url": f"https://remoteok.com/remote-jobs/{job_id}",
        "position": f"Job {job_id}",
        "date": "2026-11-10T09:00:00+00:00",
    }
    return {**job, **overrides}


def test_remoteok_skips_bad_items_and_the_source_run_succeeds() -> None:
    payload = [
        {"legal": "terms"},
        remoteok_job("1"),
        {"id": "2", "url": "https://remoteok.com/remote-jobs/2"},  # no position
        None,
        "not an object",
        remoteok_job("3"),
        remoteok_job("4", date="not a date"),
        remoteok_job("5"),
    ]

    summary, saved = run_with_stub_save(RemoteOkSource(), payload)

    assert summary.status == STATUS_OK
    assert [row["source_id"] for row in saved] == ["1", "3", "5"]
    assert (summary.fetched, summary.failed) == (3, 2)


def remotive_job(job_id: int, **overrides) -> dict:
    job = {
        "id": job_id,
        "url": f"https://remotive.com/remote-jobs/{job_id}",
        "title": f"Job {job_id}",
        "company_name": "Beta Corp",
        "candidate_required_location": "Worldwide",
    }
    return {**job, **overrides}


def test_remotive_skips_bad_items_and_the_source_run_succeeds() -> None:
    no_title = {k: v for k, v in remotive_job(2).items() if k != "title"}
    no_url = {k: v for k, v in remotive_job(3).items() if k != "url"}
    payload = {
        "job-count": 6,
        "jobs": [
            remotive_job(1),
            no_title,
            no_url,
            None,
            remotive_job(4, publication_date="not a date"),
            remotive_job(5),
        ],
    }

    summary, saved = run_with_stub_save(RemotiveSource(), payload)

    assert summary.status == STATUS_OK
    assert [row["source_id"] for row in saved] == ["1", "5"]
    assert (summary.fetched, summary.failed) == (2, 4)


def test_remotive_keeps_jobs_that_lack_optional_company_and_location() -> None:
    job = {"id": 7, "url": "https://remotive.com/remote-jobs/7", "title": "Bare Job"}

    summary, saved = run_with_stub_save(RemotiveSource(), {"jobs": [job]})

    assert summary.status == STATUS_OK
    assert [(row["source_id"], row["company"], row["location"]) for row in saved] == [
        ("7", None, None)
    ]
