"""The authentication stage of the end-to-end test.

The same pipeline runs behind an API that needs real credentials: bearer JWTs (HS256), a static
API key and stream tokens, with no development bypass. Two owners, alice and bob, each save a
profile with their own token; the tests show that every route is scoped to the caller, what a
missing, invalid or expired credential gets, how the live feed authenticates (a bearer header,
or the short-lived stream token that a browser `EventSource` uses) and that rate limits are
per owner and leave streams alone.

Valid streams are read with the streaming ASGI client (`sse.py`); `TestClient` is used only for
requests that are answered at once (401, 404, 429), because it never sees the end of a stream.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests import auth_helpers
from tests.e2e import data, sse
from tests.e2e import pipeline as p

T = TypeVar("T")

ALICE = auth_helpers.bearer(auth_helpers.token(sub="alice"))
BOB = auth_helpers.bearer(auth_helpers.token(sub="bob"))
OPS = auth_helpers.bearer(auth_helpers.API_KEY)
EXPIRED = auth_helpers.bearer(auth_helpers.token(sub="alice", exp=int(time.time()) - 3600))
WRONG_SECRET = auth_helpers.bearer(auth_helpers.token(secret="another-secret-of-32-characters-xx"))
GARBAGE = auth_helpers.bearer("not-a-jwt")
BAD_CREDENTIALS = {
    "no credential": {},
    "wrong signing secret": WRONG_SECRET,
    "expired token": EXPIRED,
    "not a token": GARBAGE,
}


def run(scenario: Callable[[], Awaitable[T]]) -> T:
    async def wrapper() -> T:
        return await scenario()

    return asyncio.run(wrapper())


class Auth:
    """An authenticated app with alice's and bob's profile (same criteria), ready to match."""

    def __init__(self, stack: p.Stack) -> None:
        self.stack = stack
        self.app: FastAPI = p.api_app(stack)
        self.client = TestClient(self.app)
        self.alice_profile = p.create_profile(self.client, data.PROFILE_BODY, ALICE)["id"]
        self.bob_profile = p.create_profile(self.client, data.PROFILE_BODY, BOB)["id"]
        assert p.drain_queue(stack) == 4  # embed and match each profile; no jobs exist yet

    def matches(self, profile_id: int, headers: dict[str, str]) -> list[dict[str, Any]]:
        return p.matches_of(self.client, profile_id, headers=headers)

    def match_ids(self, profile_id: int, headers: dict[str, str]) -> list[int]:
        return [m["id"] for m in self.matches(profile_id, headers)]

    def stream_token(self, profile_id: int, headers: dict[str, str]) -> dict[str, Any]:
        response = self.client.post(
            "/auth/stream-token", json={"profile_id": profile_id}, headers=headers
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
def auth(clean_db: Engine) -> Auth:
    return Auth(p.build_auth_stack(clean_db))


def assert_envelope(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"], "the error carries the request id"
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


# -- who may call ----------------------------------------------------------------------------


@pytest.mark.parametrize("credential", BAD_CREDENTIALS.values(), ids=BAD_CREDENTIALS.keys())
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/profiles"),
        ("POST", "/profiles"),
        ("POST", "/auth/stream-token"),
        ("GET", "/profiles/1/matches"),
        ("GET", "/profiles/1/matches/stream"),
    ],
)
def test_a_missing_invalid_or_expired_credential_is_a_401_with_the_error_envelope(
    auth: Auth, method: str, path: str, credential: dict[str, str]
) -> None:
    response = auth.client.request(method, path, json={}, headers=credential)

    error = assert_envelope(response, 401, "unauthenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"
    sent = credential.get("Authorization", "").removeprefix("Bearer ")
    assert not sent or sent not in response.text, "the answer never repeats the credential"
    assert error["message"]


def test_health_probes_need_no_credential(auth: Auth) -> None:
    assert auth.client.get("/healthz").status_code == 200
    assert auth.client.get("/readyz").status_code == 200


def test_an_api_key_authenticates_as_its_owner_and_sees_only_its_own_profiles(auth: Auth) -> None:
    ops_profile = p.create_profile(auth.client, data.PROFILE_BODY, OPS)

    assert [x["id"] for x in auth.client.get("/profiles", headers=OPS).json()["items"]] == [
        ops_profile["id"]
    ]
    assert auth.client.get(f"/profiles/{ops_profile['id']}", headers=ALICE).status_code == 404
    listed_by_alice = auth.client.get("/profiles", headers=ALICE).json()["items"]
    assert [x["id"] for x in listed_by_alice] == [auth.alice_profile]
    wrong_key = auth_helpers.bearer(auth_helpers.API_KEY + "x")
    assert auth.client.get("/profiles", headers=wrong_key).status_code == 401


# -- scoping -----------------------------------------------------------------------------------


def test_each_owner_gets_their_own_matches_and_a_foreign_profile_is_a_404(auth: Auth) -> None:
    p.run_pipeline(auth.stack, data.first_run_feeds())

    alice_ids = auth.match_ids(auth.alice_profile, ALICE)
    bob_ids = auth.match_ids(auth.bob_profile, BOB)

    assert len(alice_ids) == len(bob_ids) == len(data.EXPECTED_FIRST_MATCHES)
    assert not set(alice_ids) & set(bob_ids)
    assert p.matched_titles(auth.client, auth.alice_profile, ALICE) == data.EXPECTED_FIRST_MATCHES
    for path in (
        f"/profiles/{auth.bob_profile}",
        f"/profiles/{auth.bob_profile}/matches",
        f"/profiles/{auth.bob_profile}/matches/stream",
    ):
        error = assert_envelope(auth.client.get(path, headers=ALICE), 404, "not_found")
        assert str(auth.bob_profile) not in error["message"], "ids reveal nothing"
    missing = auth.client.get("/profiles/99999", headers=ALICE)
    assert (
        missing.status_code == 404
        and missing.json()["error"]["message"]
        == (
            auth.client.get(f"/profiles/{auth.bob_profile}", headers=ALICE).json()["error"][
                "message"
            ]
        )
    )
    assert auth.client.delete(f"/profiles/{auth.bob_profile}", headers=ALICE).status_code == 404
    assert auth.client.get(f"/profiles/{auth.bob_profile}", headers=BOB).status_code == 200
    assert [x["id"] for x in auth.client.get("/profiles", headers=BOB).json()["items"]] == [
        auth.bob_profile
    ]


# -- search ------------------------------------------------------------------------------------


def test_search_is_public_and_opens_nothing_else(auth: Auth) -> None:
    p.run_pipeline(auth.stack, data.first_run_feeds())

    assert p.search_titles(auth.client, "kubernetes")[0] == data.DEVOPS
    assert p.search_titles(auth.client, "kubernetes", ALICE)[0] == data.DEVOPS
    assert p.search_titles(auth.client, "kubernetes", OPS)[0] == data.DEVOPS
    assert auth.client.get("/profiles").status_code == 401


# -- the live feed -----------------------------------------------------------------------------


def test_a_bearer_credential_opens_the_stream_of_the_owners_own_profile(auth: Auth) -> None:
    async def scenario() -> tuple[list[sse.MatchEvent], list[sse.MatchEvent], bool]:
        alice = await sse.open_live(auth.app, auth.alice_profile, headers=ALICE)
        bob = await sse.open_live(auth.app, auth.bob_profile, headers=BOB)
        p.run_pipeline(auth.stack, data.first_run_feeds())
        alice_events = await alice.events(len(data.EXPECTED_FIRST_MATCHES))
        bob_events = await bob.events(len(data.EXPECTED_FIRST_MATCHES))
        quiet = await alice.quiet() and await bob.quiet()
        await alice.close()
        await bob.close()
        return alice_events, bob_events, quiet

    alice_events, bob_events, quiet = run(scenario)

    assert quiet
    assert sorted(e.id for e in alice_events) == auth.match_ids(auth.alice_profile, ALICE)
    assert sorted(e.id for e in bob_events) == auth.match_ids(auth.bob_profile, BOB)
    assert auth.stack.redis is not None and auth.stack.redis.closed


def test_a_stream_token_opens_the_stream_of_its_profile_and_delivers_its_matches(
    auth: Auth,
) -> None:
    minted = auth.stream_token(auth.alice_profile, ALICE)
    assert minted["path"] == f"/profiles/{auth.alice_profile}/matches/stream"
    assert minted["query_parameter"] == "stream_token"
    assert 0 < minted["expires_in"] <= 600
    query = f"stream_token={minted['token']}"

    async def scenario() -> list[sse.MatchEvent]:
        # No Authorization header: the token alone, as a browser EventSource sends it.
        conn = await sse.open_live(auth.app, auth.alice_profile, query=query)
        p.run_pipeline(auth.stack, data.first_run_feeds())
        events = await conn.events(len(data.EXPECTED_FIRST_MATCHES))
        await conn.close()
        return events

    events = run(scenario)

    assert sorted(e.id for e in events) == auth.match_ids(auth.alice_profile, ALICE)


def test_the_stream_token_opens_nothing_but_its_stream(auth: Auth) -> None:
    alice_token = auth.stream_token(auth.alice_profile, ALICE)["token"]
    query = {"stream_token": alice_token}
    not_alices = f"/profiles/{auth.bob_profile}/matches/stream"

    for path in (
        "/profiles",
        f"/profiles/{auth.alice_profile}",
        f"/profiles/{auth.alice_profile}/matches",
    ):
        response = auth.client.get(path, params=query)
        assert_envelope(response, 401, "unauthenticated")
    # It cannot mint another token, and it is not good for another profile's stream.
    minting = auth.client.post(
        "/auth/stream-token", params=query, json={"profile_id": auth.alice_profile}
    )
    assert_envelope(minting, 401, "unauthenticated")
    assert_envelope(auth.client.get(not_alices, params=query), 401, "unauthenticated")

    async def scenario() -> list[int]:
        statuses = []
        tampered = alice_token[:-2] + ("AA" if not alice_token.endswith("AA") else "BB")
        for headers, params in [
            ({}, f"stream_token={tampered}"),  # altered signature
            (BOB, f"stream_token={alice_token}"),  # a header wins: this is bob asking for alice's
        ]:
            conn = await sse.open_sse(
                auth.app,
                f"/profiles/{auth.alice_profile}/matches/stream",
                headers=headers,
                query=params,
            )
            statuses.append(conn.status)
            await conn.close()
        return statuses

    assert run(scenario) == [401, 404]


def test_a_stream_token_cannot_be_minted_for_a_foreign_profile_or_without_a_credential(
    auth: Auth,
) -> None:
    foreign = auth.client.post(
        "/auth/stream-token", json={"profile_id": auth.bob_profile}, headers=ALICE
    )
    unknown = auth.client.post("/auth/stream-token", json={"profile_id": 99999}, headers=ALICE)

    assert_envelope(foreign, 404, "not_found")
    assert foreign.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert_envelope(
        auth.client.post("/auth/stream-token", json={"profile_id": auth.alice_profile}),
        401,
        "unauthenticated",
    )
    assert_envelope(
        auth.client.post("/auth/stream-token", json={"profile_id": 0}, headers=ALICE),
        422,
        "validation_error",
    )


# -- rate limits -------------------------------------------------------------------------------


def test_the_rate_limit_is_per_owner_and_streams_are_exempt(auth: Auth) -> None:
    limited = p.api_app(auth.stack, rate_limit_default_requests=3, rate_limit_window_seconds=60)
    client = TestClient(limited)

    answers = [client.get("/profiles", headers=ALICE) for _ in range(4)]

    assert [r.status_code for r in answers] == [200, 200, 200, 429]
    assert answers[0].headers["X-RateLimit-Limit"] == "3"
    assert answers[2].headers["X-RateLimit-Remaining"] == "0"
    error = assert_envelope(answers[3], 429, "rate_limited")
    assert int(answers[3].headers["Retry-After"]) >= 1
    assert error["message"]
    # Bob has a budget of his own.
    assert client.get("/profiles", headers=BOB).status_code == 200

    async def scenario() -> list[int]:
        statuses = []
        for _ in range(5):  # more streams than the limit allows requests, still alice's
            conn = await sse.open_sse(
                limited, f"/profiles/{auth.alice_profile}/matches/stream", headers=ALICE
            )
            statuses.append(conn.status)
            await conn.close()
        return statuses

    assert run(scenario) == [200] * 5
    assert client.get("/profiles", headers=ALICE).status_code == 429


def test_unauthenticated_callers_share_the_budget_of_their_address(auth: Auth) -> None:
    client = TestClient(p.api_app(auth.stack, rate_limit_default_requests=2))

    codes = [client.get("/profiles").status_code for _ in range(3)]

    assert codes == [401, 401, 429]
