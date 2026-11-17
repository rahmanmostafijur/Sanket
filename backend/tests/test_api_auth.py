"""Authentication and authorization through the API: 401, 403, 404 and owner isolation."""

from typing import Annotated, Any

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.api import create_app
from sanket.api.deps import get_owner_id
from sanket.auth.stream_token import StreamTokens, feed_path
from sanket.embeddings.fake import FakeEmbeddingClient
from tests.auth_helpers import (
    ALICE_HEADERS,
    API_KEY,
    STREAM_SECRET,
    auth_client,
    bearer,
    settings,
    token,
)
from tests.match_helpers import add_profile
from tests.search_helpers import add_search_job, extraction_data
from tests.test_api_profiles import BODY, seed_matches

ALICE = ALICE_HEADERS
BOB = bearer(token(sub="bob"))


def own_profile(engine: Engine, owner: str = "alice") -> int:
    return add_profile(engine, owner_id=owner, embed=False).id


# --- 401 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/profiles"),
        ("POST", "/profiles"),
        ("GET", "/profiles/1"),
        ("PUT", "/profiles/1"),
        ("PATCH", "/profiles/1"),
        ("DELETE", "/profiles/1"),
        ("GET", "/profiles/1/matches"),
        ("POST", "/auth/stream-token"),
        ("GET", "/search?q=python"),
    ],
)
def test_every_owner_route_and_search_refuse_a_request_without_credentials(
    clean_db: Engine, method: str, url: str
) -> None:
    response = auth_client(clean_db).request(method, url, json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        bearer("garbage"),
        bearer(token(exp=1)),
        bearer(token(secret="another-secret-of-at-least-32-characters!")),
        {"Authorization": "Basic YWxpY2U6cHc="},
    ],
    ids=["garbage", "expired", "wrong-signature", "wrong-scheme"],
)
def test_a_bad_credential_is_401_and_is_not_echoed(
    clean_db: Engine, headers: dict[str, str]
) -> None:
    response = auth_client(clean_db).get("/profiles", headers=headers)

    assert response.status_code == 401
    assert headers["Authorization"].split(" ")[-1] not in response.text


def test_a_valid_token_and_a_static_key_both_work(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")

    assert client.get("/profiles", headers=ALICE).status_code == 200
    assert client.get("/profiles", headers=bearer(API_KEY)).status_code == 200


# --- 403 ----------------------------------------------------------------------------------


def test_a_valid_token_without_the_required_scope_is_403(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_required_scope="sanket")

    allowed = client.get("/profiles", headers=bearer(token(scope="sanket")))
    denied = client.get("/profiles", headers=bearer(token(scope="other")))

    assert (allowed.status_code, denied.status_code) == (200, 403)
    assert "www-authenticate" not in denied.headers


# --- 404 and isolation --------------------------------------------------------------------


def test_the_owner_comes_from_the_token_not_from_the_request(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    created = client.post("/profiles", json=BODY, headers=ALICE)
    assert created.status_code == 201

    assert [p["id"] for p in client.get("/profiles", headers=ALICE).json()["items"]] == [
        created.json()["id"]
    ]
    assert client.get("/profiles", headers=BOB).json()["items"] == []


def test_another_owners_profile_is_404_on_every_route(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db, "alice")
    client = auth_client(clean_db)
    url = f"/profiles/{profile_id}"

    responses = [
        client.get(url, headers=BOB),
        client.put(url, json=BODY, headers=BOB),
        client.patch(url, json={"summary": "x"}, headers=BOB),
        client.delete(url, headers=BOB),
        client.get(f"{url}/matches", headers=BOB),
        client.post("/auth/stream-token", json={"profile_id": profile_id}, headers=BOB),
    ]

    assert [r.status_code for r in responses] == [404] * 6
    assert client.get(url, headers=ALICE).status_code == 200


def test_matches_of_a_profile_are_not_readable_by_another_owner(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db, "alice")
    seed_matches(clean_db, profile_id, 2)
    client = auth_client(clean_db)

    assert len(client.get(f"/profiles/{profile_id}/matches", headers=ALICE).json()["items"]) == 2
    assert client.get(f"/profiles/{profile_id}/matches", headers=BOB).status_code == 404


def test_a_static_key_acts_as_its_named_owner(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db, "svc")
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")

    assert client.get(f"/profiles/{profile_id}", headers=bearer(API_KEY)).status_code == 200
    assert client.get(f"/profiles/{profile_id}", headers=ALICE).status_code == 404


# --- public routes and search policy -------------------------------------------------------


def test_search_is_open_only_when_configured(clean_db: Engine) -> None:
    add_search_job(clean_db, title="Python Developer", extraction=extraction_data())
    open_client = auth_client(clean_db, search_public=True)

    assert open_client.get("/search", params={"q": "python"}).status_code == 200
    assert auth_client(clean_db).get("/search", params={"q": "python"}).status_code == 401
    assert auth_client(clean_db).get("/search", params={"q": "p"}, headers=ALICE).status_code == 200


def test_search_does_not_open_the_profile_routes(clean_db: Engine) -> None:
    client = auth_client(clean_db, search_public=True)

    assert client.get("/profiles").status_code == 401


def test_a_global_dependency_still_guards_every_api_route(clean_db: Engine) -> None:
    def deny() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=418, detail="no")

    app = create_app(settings(), clean_db, FakeEmbeddingClient(), dependencies=[Depends(deny)])

    assert TestClient(app).get("/profiles", headers=ALICE).status_code == 418


def test_the_dev_bypass_acts_as_the_default_owner_and_a_bad_token_still_fails(
    clean_db: Engine,
) -> None:
    profile_id = own_profile(clean_db, "dev")
    client = auth_client(
        clean_db, auth_jwt_secret=None, auth_dev_bypass=True, default_owner_id="dev"
    )

    assert client.get(f"/profiles/{profile_id}").status_code == 200
    assert client.get(f"/profiles/{profile_id}", headers=bearer("bad")).status_code == 401


def test_the_dev_bypass_cannot_be_started_in_production(clean_db: Engine) -> None:
    with pytest.raises(Exception, match="AUTH_DEV_BYPASS"):
        auth_client(clean_db, auth_dev_bypass=True, environment="production")


# --- stream tokens ------------------------------------------------------------------------


def stream_app(engine: Engine, **overrides: Any) -> TestClient:
    """The app plus a stand-in for the feed route, which uses get_owner_id like the real one."""
    app = create_app(
        settings(auth_stream_token_secret=STREAM_SECRET, **overrides), engine, FakeEmbeddingClient()
    )

    def stream(profile_id: int, owner: Annotated[str, Depends(get_owner_id)]) -> dict[str, Any]:
        return {"owner": owner, "profile_id": profile_id}

    app.add_api_route("/profiles/{profile_id}/matches/stream", stream)
    return TestClient(app)


def mint(client: TestClient, profile_id: int, headers: dict[str, str] = ALICE) -> dict[str, Any]:
    response = client.post("/auth/stream-token", json={"profile_id": profile_id}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_minted_token_opens_the_stream_of_its_own_profile(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db)
    client = stream_app(clean_db)

    minted = mint(client, profile_id)
    response = client.get(minted["path"], params={minted["query_parameter"]: minted["token"]})

    assert minted["path"] == feed_path(profile_id) and minted["expires_in"] == 60
    assert response.json() == {"owner": "alice", "profile_id": profile_id}


def test_a_stream_token_opens_nothing_else(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db)
    client = stream_app(clean_db)
    value = mint(client, profile_id)["token"]

    assert client.get("/profiles", params={"stream_token": value}).status_code == 401
    other = client.get(feed_path(profile_id + 1), params={"stream_token": value})
    assert other.status_code == 401
    assert client.get(feed_path(profile_id), params={"stream_token": "junk"}).status_code == 401
    assert client.get(feed_path(profile_id)).status_code == 401


def test_a_stream_token_cannot_mint_another_one(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db)
    client = stream_app(clean_db)
    value = mint(client, profile_id)["token"]

    response = client.post(
        "/auth/stream-token?stream_token=" + value, json={"profile_id": profile_id}
    )

    assert response.status_code == 401


def test_an_expired_stream_token_is_401(clean_db: Engine) -> None:
    client = stream_app(clean_db)
    path = feed_path(1)
    expired = StreamTokens(STREAM_SECRET, 60, lambda: 1.0).mint("alice", path)

    assert client.get(path, params={"stream_token": expired}).status_code == 401


def test_the_header_still_works_on_the_stream_path(clean_db: Engine) -> None:
    client = stream_app(clean_db)

    response = client.get(feed_path(3), headers=BOB)

    assert response.json()["owner"] == "bob"


def test_without_a_secret_stream_tokens_are_off(clean_db: Engine) -> None:
    profile_id = own_profile(clean_db)
    client = auth_client(clean_db)

    response = client.post("/auth/stream-token", json={"profile_id": profile_id}, headers=ALICE)

    assert response.status_code == 404
