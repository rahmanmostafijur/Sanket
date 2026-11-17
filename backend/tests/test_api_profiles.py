"""The profile endpoints through FastAPI's test client: CRUD, owner scoping, matches paging."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.models import JobMatch
from sanket.queue.base import EnqueueResult
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import TASK_EMBED_PROFILE
from tests.index_helpers import SPEC
from tests.match_helpers import OWNER, add_profile, profile_client
from tests.search_helpers import add_search_job, extraction_data
from tests.test_profile_schema import add_match

BODY: dict[str, Any] = {
    "name": "Backend",
    "summary": "backend engineer",
    "desired_titles": ["Backend Engineer"],
    "required_skills": ["Python"],
    "countries": ["de"],
}


class BrokenQueue:
    def enqueue(self, *args: object, **kwargs: object) -> EnqueueResult:
        raise ConnectionError("redis is down")


def post(client: TestClient, **changes: Any) -> Any:
    return client.post("/profiles", json={**BODY, **changes})


# --- create -------------------------------------------------------------------------------


def test_creating_returns_the_profile_pending_and_queues_its_embedding(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()
    client = profile_client(clean_db, queue)

    response = post(client)

    assert response.status_code == 201
    body = response.json()
    assert body["embedding_status"] == "pending"
    assert body["countries"] == ["DE"]
    assert (body["name"], body["active"], body["min_score_override"]) == ("Backend", True, None)
    assert body["seniorities"] == [] and body["summary"] == "backend engineer"
    [task] = queue.pending(TASK_EMBED_PROFILE)
    assert task.payload["profile_id"] == body["id"]


def test_creating_does_not_call_the_embedding_provider(clean_db: Engine) -> None:
    provider = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    client = profile_client(clean_db, InMemoryTaskQueue(), provider=provider)

    post(client)

    assert provider.query_calls == [] and provider.document_calls == []


def test_the_same_create_twice_is_one_profile_and_returns_200(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()
    client = profile_client(clean_db, queue)

    first = post(client)
    second = post(client)

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/profiles").json()["items"]) == 1
    assert len(queue.pending()) == 1


def test_the_same_name_with_different_content_is_409(clean_db: Engine) -> None:
    client = profile_client(clean_db)
    post(client)

    assert post(client, summary="different").status_code == 409


def test_the_profile_limit_is_409(clean_db: Engine) -> None:
    client = profile_client(clean_db, max_profiles_per_owner=2)

    codes = [post(client, name=f"p{n}").status_code for n in range(3)]

    assert codes == [201, 201, 409]


def test_a_queue_failure_still_creates_the_profile(clean_db: Engine) -> None:
    client = profile_client(clean_db, BrokenQueue())

    response = post(client)

    assert response.status_code == 201
    assert response.json()["embedding_status"] == "pending"


def test_creating_works_without_a_queue(clean_db: Engine) -> None:
    assert post(profile_client(clean_db, None)).status_code == 201


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"summary": "x" * 2001},
        {"required_skills": ["s"] * 21},
        {"desired_titles": ["t" * 101]},
        {"countries": ["XX"]},
        {"seniorities": ["wizard"]},
        {"work_modes": ["unknown"]},
        {"min_score_override": 1.5},
        {"unexpected": True},
        {"summary": "", "desired_titles": [], "required_skills": []},
        {"summary": "a\u0000b"},
    ],
)
def test_invalid_bodies_are_422(clean_db: Engine, changes: dict[str, Any]) -> None:
    client = profile_client(clean_db)

    assert post(client, **changes).status_code == 422
    assert client.get("/profiles").json() == {"items": []}


def test_a_body_that_is_not_an_object_is_422(clean_db: Engine) -> None:
    client = profile_client(clean_db)

    assert client.post("/profiles", json=[1, 2]).status_code == 422
    assert client.post("/profiles", content="not json").status_code == 422


# --- read and owner scoping ---------------------------------------------------------------


def test_listing_and_getting_return_only_your_own_profiles(clean_db: Engine) -> None:
    mine = post(profile_client(clean_db, owner="a")).json()
    theirs = post(profile_client(clean_db, owner="b")).json()
    client_a = profile_client(clean_db, owner="a")
    client_b = profile_client(clean_db, owner="b")

    assert [p["id"] for p in client_a.get("/profiles").json()["items"]] == [mine["id"]]
    assert [p["id"] for p in client_b.get("/profiles").json()["items"]] == [theirs["id"]]
    assert client_a.get(f"/profiles/{mine['id']}").json()["name"] == "Backend"


def test_another_owners_profile_is_404_on_every_route(clean_db: Engine) -> None:
    mine = post(profile_client(clean_db, owner="a")).json()
    other = profile_client(clean_db, owner="b")
    url = f"/profiles/{mine['id']}"

    responses = [
        other.get(url),
        other.put(url, json=BODY),
        other.patch(url, json={"summary": "x"}),
        other.delete(url),
        other.get(f"{url}/matches"),
    ]

    assert [r.status_code for r in responses] == [404] * 5
    assert profile_client(clean_db, owner="a").get(url).status_code == 200


def test_an_unknown_profile_is_404_and_a_bad_id_is_422(clean_db: Engine) -> None:
    client = profile_client(clean_db)

    assert client.get("/profiles/999").status_code == 404
    assert client.get("/profiles/abc").status_code == 422


def test_the_status_becomes_ready_once_the_profile_is_embedded(clean_db: Engine) -> None:
    client = profile_client(clean_db)
    profile_id = post(client).json()["id"]
    assert client.get(f"/profiles/{profile_id}").json()["embedding_status"] == "pending"

    from sanket.embeddings.fake import FakeEmbeddingClient
    from sanket.profiles.embedding import embed_profile

    embed_profile(profile_id, FakeEmbeddingClient(), SPEC, db_engine=clean_db)

    assert client.get(f"/profiles/{profile_id}").json()["embedding_status"] == "ready"


# --- replace, patch, delete ---------------------------------------------------------------


def test_put_replaces_everything_and_goes_back_to_pending(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()
    profile = add_profile(clean_db)
    client = profile_client(clean_db, queue)

    response = client.put(
        f"/profiles/{profile.id}",
        json={"name": "Backend", "summary": "new text", "work_modes": ["remote"]},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["summary"] == "new text" and body["work_modes"] == ["remote"]
    assert body["required_skills"] == [] and body["embedding_status"] == "pending"
    assert len(queue.pending(TASK_EMBED_PROFILE)) == 1


def test_put_with_a_taken_name_is_409(clean_db: Engine) -> None:
    add_profile(clean_db, name="taken")
    other = add_profile(clean_db, name="other")
    client = profile_client(clean_db)

    response = client.put(f"/profiles/{other.id}", json={**BODY, "name": "taken"})

    assert response.status_code == 409


def test_patch_changes_only_what_is_sent(clean_db: Engine) -> None:
    profile = add_profile(clean_db, required_skills=["Python"])
    client = profile_client(clean_db)

    response = client.patch(
        f"/profiles/{profile.id}", json={"active": False, "locations": ["Berlin"]}
    )

    body = response.json()
    assert response.status_code == 200
    assert (body["active"], body["locations"], body["required_skills"]) == (
        False,
        ["Berlin"],
        ["Python"],
    )


def test_patch_null_clears_the_score_override(clean_db: Engine) -> None:
    profile = add_profile(clean_db, min_score_override=0.8)
    client = profile_client(clean_db)

    response = client.patch(f"/profiles/{profile.id}", json={"min_score_override": None})

    assert response.json()["min_score_override"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"countries": ["ZZ"]},
        {"unknown": 1},
        {"name": ""},
        {"summary": None},
        {"required_skills": ["s"] * 21},
    ],
)
def test_an_invalid_patch_is_422_and_changes_nothing(
    clean_db: Engine, patch: dict[str, Any]
) -> None:
    profile = add_profile(clean_db)
    client = profile_client(clean_db)

    assert client.patch(f"/profiles/{profile.id}", json=patch).status_code == 422
    assert client.get(f"/profiles/{profile.id}").json()["summary"] == profile.criteria["summary"]


def test_a_patch_that_would_empty_the_profile_is_422(clean_db: Engine) -> None:
    profile = add_profile(clean_db, desired_titles=[], summary="only a summary")
    client = profile_client(clean_db)

    assert client.patch(f"/profiles/{profile.id}", json={"summary": ""}).status_code == 422


def test_delete_is_204_then_404(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    client = profile_client(clean_db)

    assert client.delete(f"/profiles/{profile.id}").status_code == 204
    assert client.delete(f"/profiles/{profile.id}").status_code == 404
    assert client.get("/profiles").json() == {"items": []}


# --- matches ------------------------------------------------------------------------------


def seed_matches(engine: Engine, profile_id: int, count: int) -> list[int]:
    ids = []
    for number in range(count):
        job_id = add_search_job(
            engine,
            title=f"Engineer {number}",
            source="remoteok",
            url=f"https://remoteok.com/{number}",
            extraction=extraction_data(),
        )
        ids.append(add_match(engine, profile_id, job_id, score=0.6 + number / 100))
    return ids


def test_matches_page_forward_by_id_without_gaps_or_repeats(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    ids = seed_matches(clean_db, profile.id, 5)
    client = profile_client(clean_db)
    url = f"/profiles/{profile.id}/matches"

    first = client.get(url, params={"limit": 2}).json()
    second = client.get(url, params={"limit": 2, "after_id": first["next_after_id"]}).json()
    third = client.get(url, params={"limit": 2, "after_id": second["next_after_id"]}).json()
    empty = client.get(url, params={"after_id": third["next_after_id"]}).json()

    assert [m["id"] for m in first["items"]] == ids[:2] and first["has_more"] is True
    assert [m["id"] for m in second["items"]] == ids[2:4] and second["has_more"] is True
    assert [m["id"] for m in third["items"]] == ids[4:] and third["has_more"] is False
    assert empty == {"items": [], "next_after_id": None, "has_more": False}


def test_a_match_carries_the_score_components_and_the_job_with_its_credit(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    [match_id] = seed_matches(clean_db, profile.id, 1)
    client = profile_client(clean_db)

    [item] = client.get(f"/profiles/{profile.id}/matches").json()["items"]

    assert item["id"] == match_id and item["status"] == "active"
    assert item["score"] == pytest.approx(0.6)
    assert item["components"] == {}
    job = item["job"]
    assert job["title"] == "Engineer 0" and job["url"] == "https://remoteok.com/0"
    assert job["source_name"] == "Remote OK" and job["attribution"]
    assert job["extracted"]["skills"] == ["Python", "PostgreSQL"]


def test_withdrawn_matches_are_hidden_unless_asked_for(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    ids = seed_matches(clean_db, profile.id, 2)
    from sqlalchemy import update

    with clean_db.begin() as conn:
        conn.execute(update(JobMatch).where(JobMatch.id == ids[0]).values(status="withdrawn"))
    client = profile_client(clean_db)
    url = f"/profiles/{profile.id}/matches"

    assert [m["id"] for m in client.get(url).json()["items"]] == [ids[1]]
    shown = client.get(url, params={"include_withdrawn": True}).json()["items"]
    assert [(m["id"], m["status"]) for m in shown] == [(ids[0], "withdrawn"), (ids[1], "active")]


def test_matches_of_other_profiles_are_not_listed(clean_db: Engine) -> None:
    mine = add_profile(clean_db, name="mine")
    other = add_profile(clean_db, name="other")
    seed_matches(clean_db, other.id, 2)
    client = profile_client(clean_db)

    assert client.get(f"/profiles/{mine.id}/matches").json()["items"] == []


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"after_id": -1}, {"after_id": "x"}]
)
def test_bad_match_paging_parameters_are_422(clean_db: Engine, params: dict[str, Any]) -> None:
    profile = add_profile(clean_db)

    response = profile_client(clean_db).get(f"/profiles/{profile.id}/matches", params=params)

    assert response.status_code == 422


def test_the_routes_are_documented_in_the_openapi_schema(clean_db: Engine) -> None:
    paths = profile_client(clean_db).get("/openapi.json").json()["paths"]

    assert set(paths["/profiles"]) == {"get", "post"}
    assert set(paths["/profiles/{profile_id}"]) == {"get", "put", "patch", "delete"}
    assert "/profiles/{profile_id}/matches" in paths


def test_the_default_owner_is_the_configured_one(clean_db: Engine) -> None:
    created = post(profile_client(clean_db, owner="someone")).json()

    assert (
        profile_client(clean_db, owner="someone").get(f"/profiles/{created['id']}").status_code
        == 200
    )
    assert (
        profile_client(clean_db, owner=OWNER).get(f"/profiles/{created['id']}").status_code == 404
    )
