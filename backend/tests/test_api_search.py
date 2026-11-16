"""`GET /search` through FastAPI's test client, against the test database and the fake embedder."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, update

from sanket.api import create_app
from sanket.config import Settings
from sanket.embeddings.client import EmbeddingError
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.models import Posting
from tests.index_helpers import (
    SPEC,
    add_indexable_job,
    representative_posting_id,
    set_posting_count,
)
from tests.search_helpers import (
    add_search_job,
    api_client,
    extraction_data,
    index_everything,
    seed_filter_corpus,
)


def get(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/search", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def titles(body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in body["items"]]


def ids(body: dict[str, Any]) -> list[int]:
    return [item["job_id"] for item in body["items"]]


class FailingQueryClient(FakeEmbeddingClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        raise self.error


# --- response shape ----------------------------------------------------------------------


def test_a_result_carries_the_job_its_posting_link_and_the_extracted_fields(
    clean_db: Engine,
) -> None:
    job_id = add_search_job(
        clean_db,
        title="Senior Python Engineer",
        company="Acme",
        location="Berlin",
        source="remoteok",
        url="https://remoteok.com/remote-jobs/1",
        published_at=datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
        extraction=extraction_data(
            skills=["Python", "Go"],
            salary={"min_amount": 50000, "max_amount": 80000, "currency": "USD", "period": "year"},
        ),
    )
    client = api_client(clean_db, index_everything(clean_db))

    body = get(client, q="python")

    assert (body["query"], body["limit"], body["offset"]) == ("python", 20, 0)
    assert (body["total_candidates"], body["has_more"], body["degraded"]) == (1, False, False)
    assert body["degraded_reason"] is None
    (item,) = body["items"]
    assert item["job_id"] == job_id
    assert (item["title"], item["company"], item["location"]) == (
        "Senior Python Engineer",
        "Acme",
        "Berlin",
    )
    assert item["url"] == "https://remoteok.com/remote-jobs/1"
    assert item["published_at"].startswith("2026-11-01T09:00:00")
    assert item["matched_by"] == "both"
    assert item["score"] > 0
    assert item["extracted"] == {
        "work_mode": "remote",
        "seniority": "senior",
        "employment_type": "full_time",
        "country": "DE",
        "city": "Berlin",
        "skills": ["Python", "Go"],
        "min_years_experience": 3,
        "salary": {"min_amount": 50000, "max_amount": 80000, "currency": "USD", "period": "year"},
    }


def test_a_job_without_an_extraction_has_null_extracted_fields(clean_db: Engine) -> None:
    add_search_job(clean_db, title="Plumber")
    client = api_client(clean_db, index_everything(clean_db))

    (item,) = get(client, q="plumber")["items"]

    assert item["extracted"] is None


@pytest.mark.parametrize(
    ("source", "name", "attribution"),
    [
        ("remoteok", "Remote OK", "Job listing from Remote OK"),
        ("remotive", "Remotive", "Job listing from Remotive"),
        ("greenhouse", "Greenhouse", None),
    ],
)
def test_results_name_and_credit_their_source(
    clean_db: Engine, source: str, name: str, attribution: str | None
) -> None:
    add_search_job(clean_db, title="Plumber", source=source, url=f"https://example.test/{source}")
    client = api_client(clean_db, index_everything(clean_db))

    (item,) = get(client, q="plumber")["items"]

    assert item["source"] == source
    assert item["source_name"] == name
    assert item["attribution"] == attribution
    assert item["url"] == f"https://example.test/{source}"
    assert item["sources"] == [{"source": source, "name": name}]


def test_a_job_listed_on_several_sources_names_them_all(clean_db: Engine) -> None:
    job_id = add_search_job(clean_db, title="Plumber", source="remotive", url="https://r.test/1")
    with clean_db.begin() as conn:
        conn.execute(
            insert(Posting).values(
                source="weworkremotely",
                source_id="other",
                raw={},
                content_hash="h",
                title="Plumber",
                company="Acme",
                job_id=job_id,
            )
        )
    client = api_client(clean_db, index_everything(clean_db))

    (item,) = get(client, q="plumber")["items"]

    assert item["source"] == "remotive"
    assert {entry["source"] for entry in item["sources"]} == {"remotive", "weworkremotely"}
    assert len(get(client, q="plumber", source="weworkremotely")["items"]) == 1


def test_openapi_documents_the_endpoint_and_an_example(clean_db: Engine) -> None:
    client = api_client(clean_db, FakeEmbeddingClient())

    spec = client.get("/openapi.json").json()

    operation = spec["paths"]["/search"]["get"]
    assert {param["name"] for param in operation["parameters"]} >= {"q", "limit", "work_mode"}
    assert spec["components"]["schemas"]["SearchResponse"]["examples"]


# --- retrieval behaviour -----------------------------------------------------------------


def test_matched_by_tells_text_vector_and_both_apart(clean_db: Engine) -> None:
    both = add_search_job(clean_db, title="Python Developer", description="<p>Code.</p>")
    text_only = add_search_job(
        clean_db, title="Python Developer Wizard", source="remoteok", description="<p>Code.</p>"
    )
    vector_only = add_search_job(clean_db, title="Backend Engineer", description="<p>Services.</p>")
    # Full text needs both words, so the third job is not a text match; it has an embedding, and
    # the second job has none (its source is excluded from embedding).
    client = api_client(clean_db, index_everything(clean_db, excluded_sources=("remoteok",)))

    body = get(client, q="python developer")
    by_id = {item["job_id"]: item["matched_by"] for item in body["items"]}

    assert by_id == {both: "both", text_only: "text", vector_only: "vector"}


def test_a_job_with_no_embedding_is_found_by_text_only(clean_db: Engine) -> None:
    text_only = add_search_job(clean_db, title="Python Wizard", source="remoteok")
    add_search_job(clean_db, title="Pastry Chef", description="<p>Bread.</p>")
    client = api_client(clean_db, index_everything(clean_db, excluded_sources=("remoteok",)))

    body = get(client, q="wizard")

    assert text_only in ids(body)
    match = next(item for item in body["items"] if item["job_id"] == text_only)
    assert match["matched_by"] == "text"


def test_a_job_can_be_found_by_vector_similarity_alone(clean_db: Engine) -> None:
    close = add_search_job(clean_db, title="Backend Developer", description="<p>Python.</p>")
    index = index_everything(clean_db)
    client = api_client(clean_db, index)

    # No job contains both words, so full text finds nothing; the shared word makes the vector
    # of the nearest job closest.
    body = get(client, q="python plumber")

    assert ids(body)[0] == close
    assert body["items"][0]["matched_by"] == "vector"


def test_a_query_in_another_language_finds_its_job(clean_db: Engine) -> None:
    swedish = add_search_job(
        clean_db, title="Systemutvecklare", description="<p>Vi söker en utvecklare i Malmö.</p>"
    )
    bengali = add_search_job(
        clean_db, title="ডেভেলপার", description="<p>আমরা একজন সফটওয়্যার ইঞ্জিনিয়ার খুঁজছি</p>"
    )
    add_search_job(clean_db, title="Data Analyst", description="<p>Dashboards.</p>")
    client = api_client(clean_db, index_everything(clean_db))

    assert ids(get(client, q="malmö"))[0] == swedish
    assert ids(get(client, q="সফটওয়্যার"))[0] == bengali


def test_dead_jobs_never_appear(clean_db: Engine) -> None:
    dead = add_indexable_job(clean_db, title="Python Dead")
    alive = add_indexable_job(clean_db, title="Python Alive")
    client = api_client(clean_db, index_everything(clean_db))
    set_posting_count(clean_db, dead, 0)

    assert ids(get(client, q="python")) == [alive]


# --- degraded mode -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [EmbeddingError("quota"), TimeoutError("slow"), RuntimeError("x")]
)
def test_a_failing_embedding_provider_degrades_to_full_text(
    clean_db: Engine, error: Exception
) -> None:
    job_id = add_search_job(clean_db, title="Python Developer")
    index_everything(clean_db)
    client = api_client(clean_db, FailingQueryClient(error))

    body = get(client, q="python")

    assert body["degraded"] is True
    assert body["degraded_reason"] == "embedding_failed"
    assert ids(body) == [job_id]
    assert body["items"][0]["matched_by"] == "text"


def test_disabled_embeddings_degrade_the_same_way(clean_db: Engine) -> None:
    job_id = add_search_job(clean_db, title="Python Developer")
    index_everything(clean_db)
    client = api_client(clean_db, None)

    body = get(client, q="python")

    assert (body["degraded"], body["degraded_reason"]) == (True, "embeddings_disabled")
    assert ids(body) == [job_id]


def test_the_query_embedding_is_cached_across_pages(clean_db: Engine) -> None:
    for n in range(4):
        add_search_job(clean_db, title=f"Python Developer {n}")
    embedder = index_everything(clean_db)
    client = api_client(clean_db, embedder)

    get(client, q="python developer", limit=2, offset=0)
    get(client, q="  Python   Developer ", limit=2, offset=2)

    assert len(embedder.query_calls) == 1


# --- pagination --------------------------------------------------------------------------


def seed_many(engine: Engine, count: int) -> list[int]:
    return [
        add_search_job(
            engine,
            title=f"Python Developer {n}",
            description=f"<p>Python services and tooling number {n}.</p>",
        )
        for n in range(count)
    ]


def test_pages_are_disjoint_and_cover_the_whole_list(clean_db: Engine) -> None:
    seed_many(clean_db, 12)
    client = api_client(clean_db, index_everything(clean_db))

    everything = get(client, q="python developer", limit=50)
    pages = [get(client, q="python developer", limit=5, offset=offset) for offset in (0, 5, 10)]

    paged = [job_id for page in pages for job_id in ids(page)]
    assert paged == ids(everything)
    assert len(set(paged)) == 12
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert {page["total_candidates"] for page in pages} == {12}


def test_the_candidate_cap_bounds_the_paged_list(clean_db: Engine) -> None:
    seed_many(clean_db, 12)
    client = api_client(clean_db, index_everything(clean_db), search_candidates=8)

    first = get(client, q="python developer", limit=5)
    second = get(client, q="python developer", limit=5, offset=5)
    beyond = get(client, q="python developer", limit=5, offset=8)
    far = get(client, q="python developer", limit=5, offset=1000)

    assert first["total_candidates"] == 8
    assert (len(first["items"]), first["has_more"]) == (5, True)
    assert (len(second["items"]), second["has_more"]) == (3, False)
    assert (beyond["items"], beyond["has_more"], beyond["total_candidates"]) == ([], False, 8)
    assert far["items"] == []


def test_an_offset_past_the_end_of_a_short_list_is_empty_not_an_error(clean_db: Engine) -> None:
    add_search_job(clean_db, title="Python Developer")
    client = api_client(clean_db, index_everything(clean_db))

    body = get(client, q="python", offset=20)

    assert (body["items"], body["has_more"], body["total_candidates"]) == ([], False, 1)


def test_the_ranking_is_stable_between_identical_requests(clean_db: Engine) -> None:
    seed_many(clean_db, 8)
    client = api_client(clean_db, index_everything(clean_db))

    assert ids(get(client, q="python developer")) == ids(get(client, q="python developer"))


# --- filters over HTTP -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"work_mode": "remote"}, {"remote_senior"}),
        ({"work_mode": ["remote", "hybrid"]}, {"remote_senior", "hybrid_junior"}),
        ({"seniority": "lead"}, {"onsite_lead"}),
        ({"employment_type": ["part_time", "contract"]}, {"hybrid_junior", "onsite_lead"}),
        ({"country": "se"}, {"hybrid_junior"}),
        ({"country": ["SE", "bd"]}, {"hybrid_junior", "onsite_lead"}),
        ({"source": "lever"}, {"hybrid_junior"}),
        ({"company": "ACME"}, {"remote_senior"}),
        ({"location": "dhaka"}, {"onsite_lead"}),
        ({"posted_after": "2026-09-15"}, {"remote_senior", "hybrid_junior", "no_extraction"}),
        ({"posted_after": "2026-10-15T00:00:00Z"}, {"remote_senior", "no_extraction"}),
        ({"posted_after": "2026-10-15T00:00:00"}, {"remote_senior", "no_extraction"}),
        ({"skills": "python"}, {"remote_senior", "hybrid_junior"}),
        ({"skills": ["python", "go"]}, {"remote_senior"}),
        ({"work_mode": "remote", "seniority": "senior", "country": "DE"}, {"remote_senior"}),
        ({"work_mode": "remote", "seniority": "junior"}, set()),
        ({"location": "  stockholm  ", "company": "zeta corp"}, {"hybrid_junior"}),
    ],
)
def test_filters_narrow_the_results(
    clean_db: Engine, params: dict[str, Any], expected: set[str]
) -> None:
    corpus = seed_filter_corpus(clean_db)
    client = api_client(clean_db, index_everything(clean_db))

    body = get(client, q="engineer", **params)

    assert set(ids(body)) == {corpus[name] for name in expected}


def test_a_restrictive_filter_still_fills_the_page(clean_db: Engine) -> None:
    for n in range(30):
        add_search_job(
            clean_db,
            title="Python Python Developer",
            description=f"<p>Python {n}</p>",
            extraction=extraction_data(work_mode="onsite"),
        )
    weak = add_search_job(
        clean_db,
        title="Office Clerk",
        description="<p>python once</p>",
        extraction=extraction_data(work_mode="remote"),
    )
    client = api_client(clean_db, index_everything(clean_db))

    assert ids(get(client, q="python", work_mode="remote", limit=5)) == [weak]


def test_location_wildcards_are_literal_over_http(clean_db: Engine) -> None:
    percent = add_search_job(clean_db, title="Engineer A", location="Remote 100% anywhere")
    add_search_job(clean_db, title="Engineer B", location="Remote EU")
    client = api_client(clean_db, index_everything(clean_db))

    assert ids(get(client, q="engineer", location="%")) == [percent]
    assert ids(get(client, q="engineer", location="_")) == []


# --- validation and hostile input --------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "x" * 201},
        {"q": "python", "limit": 51},
        {"q": "python", "limit": 0},
        {"q": "python", "limit": "many"},
        {"q": "python", "offset": -1},
        {"q": "python", "offset": 1001},
        {"q": "python", "work_mode": "sometimes"},
        {"q": "python", "seniority": "wizard"},
        {"q": "python", "employment_type": "forever"},
        {"q": "python", "country": "DEU"},
        {"q": "python", "country": "1!"},
        {"q": "python", "source": "Re Mote"},
        {"q": "python", "posted_after": "last week"},
        {"q": "python", "skills": ""},
        {"q": "python", "skills": "x" * 61},
        {"q": "python", "company": "x" * 201},
        {"q": "python", "unknown_param": "1"},
        {"q": "py\x00thon"},
        {"q": "python", "location": "a\x00b"},
        {"q": "python", "skills": "a\x00b"},
        {"q": "python", "work_mode": ["remote"] * 11},
    ],
)
def test_invalid_requests_are_rejected_with_422(clean_db: Engine, params: dict[str, Any]) -> None:
    client = api_client(clean_db, FakeEmbeddingClient())

    response = client.get("/search", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]


def test_the_query_is_trimmed_and_echoed_trimmed(clean_db: Engine) -> None:
    add_search_job(clean_db, title="Python Developer")
    client = api_client(clean_db, index_everything(clean_db))

    body = get(client, q="  python  ")

    assert body["query"] == "python"
    assert len(body["items"]) == 1


def test_a_query_of_exactly_200_characters_is_accepted(clean_db: Engine) -> None:
    client = api_client(clean_db, FakeEmbeddingClient())

    assert get(client, q="a" * 200)["items"] == []


HOSTILE = [
    "'; DROP TABLE job; --",
    "a' OR '1'='1",
    '" OR ""="',
    "%' AND 1=1 --",
    "\\",
    "!!! ((",
    "&|!:*",
    "<script>alert(1)</script>",
    "${jndi:ldap://x}",
    "../../etc/passwd",
]


@pytest.mark.parametrize("hostile", HOSTILE)
def test_hostile_text_is_data_in_every_parameter(clean_db: Engine, hostile: str) -> None:
    add_search_job(clean_db, title="Python Developer", extraction=extraction_data())
    client = api_client(clean_db, index_everything(clean_db))

    for params in (
        {"q": hostile},
        {"q": "python", "company": hostile},
        {"q": "python", "location": hostile},
        {"q": "python", "skills": hostile},
    ):
        response = client.get("/search", params=params)
        assert response.status_code == 200, (params, response.text)
        if set(params) != {"q"}:
            assert response.json()["items"] == []

    # The table is intact and still searchable.
    assert len(get(client, q="python")["items"]) == 1


def test_a_query_made_only_of_operators_returns_no_text_matches(clean_db: Engine) -> None:
    add_search_job(clean_db, title="Python Developer")
    client = api_client(clean_db, index_everything(clean_db))

    body = get(client, q="!!! ((")

    assert body["degraded"] is False
    assert all(item["matched_by"] == "vector" for item in body["items"])


# --- app wiring --------------------------------------------------------------------------


def test_a_global_dependency_guards_every_route(clean_db: Engine) -> None:
    def deny() -> None:
        raise HTTPException(status_code=401, detail="no")

    config = Settings(database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test")
    app = create_app(config, clean_db, None, dependencies=[Depends(deny)])

    assert TestClient(app).get("/search", params={"q": "python"}).status_code == 401


def test_a_client_for_another_model_is_refused_at_startup(clean_db: Engine) -> None:
    config = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test",
        embedding_model=SPEC.model_name,
        embedding_model_version=SPEC.model_version,
    )

    with pytest.raises(ValueError, match="embedding client"):
        create_app(config, clean_db, FakeEmbeddingClient(model_version="other"))


def test_without_a_key_the_app_starts_with_embeddings_disabled(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test", gemini_api_key=None
    )
    job_id = add_search_job(clean_db, title="Python Developer")
    index_everything(clean_db)
    client = TestClient(create_app(config, clean_db))

    body = get(client, q="python")

    assert body["degraded_reason"] == "embeddings_disabled"
    assert ids(body) == [job_id]


def test_posted_after_uses_the_posting_date_over_first_seen(clean_db: Engine) -> None:
    job_id = add_search_job(
        clean_db, title="Python Developer", published_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    with clean_db.begin() as conn:
        conn.execute(
            update(Posting)
            .where(Posting.id == representative_posting_id(clean_db, job_id))
            .values(published_at=datetime(2020, 1, 1, tzinfo=UTC))
        )
    client = api_client(clean_db, index_everything(clean_db))

    assert ids(get(client, q="python", posted_after="2021-01-01")) == []
    assert ids(get(client, q="python", posted_after="2019-01-01")) == [job_id]
