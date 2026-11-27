"""Rate limiting through the API: 429 with Retry-After, identities, buckets and exemptions."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.api import create_app
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.ratelimit.limiter import MemoryRateLimiter
from tests.auth_helpers import ALICE_HEADERS, bearer, settings, token

BOB_HEADERS = bearer(token(sub="bob"))


class Clock:
    def __init__(self) -> None:
        self.now = 6000.0

    def __call__(self) -> float:
        return self.now


def limited_client(
    engine: Engine, clock: Clock | None = None, **overrides: Any
) -> tuple[TestClient, Clock]:
    clock = clock or Clock()
    values = {"rate_limit_default_requests": 3, "rate_limit_search_requests": 2, **overrides}
    app = create_app(
        settings(**values), engine, FakeEmbeddingClient(), rate_limiter=MemoryRateLimiter(clock)
    )
    return TestClient(app), clock


def test_the_request_over_the_limit_is_429_with_retry_after_and_the_envelope(
    clean_db: Engine,
) -> None:
    client, _ = limited_client(clean_db)

    statuses = [client.get("/profiles", headers=ALICE_HEADERS).status_code for _ in range(4)]
    refused = client.get("/profiles", headers=ALICE_HEADERS)

    assert statuses == [200, 200, 200, 429]
    assert 1 <= int(refused.headers["retry-after"]) <= 60
    assert refused.headers["x-ratelimit-limit"] == "3"
    assert refused.headers["x-ratelimit-remaining"] == "0"
    assert refused.json()["error"]["code"] == "rate_limited"
    assert refused.json()["error"]["request_id"] == refused.headers["x-request-id"]


def test_successful_responses_report_the_remaining_budget(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)

    response = client.get("/profiles", headers=ALICE_HEADERS)

    assert response.headers["x-ratelimit-limit"] == "3"
    assert response.headers["x-ratelimit-remaining"] == "2"


def test_the_budget_comes_back_after_the_window(clean_db: Engine) -> None:
    client, clock = limited_client(clean_db)
    for _ in range(4):
        client.get("/profiles", headers=ALICE_HEADERS)

    clock.now += 125

    assert client.get("/profiles", headers=ALICE_HEADERS).status_code == 200


def test_each_owner_has_their_own_budget(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)
    for _ in range(4):
        client.get("/profiles", headers=ALICE_HEADERS)

    assert client.get("/profiles", headers=ALICE_HEADERS).status_code == 429
    assert client.get("/profiles", headers=BOB_HEADERS).status_code == 200


def test_search_has_a_stricter_limit_and_its_own_bucket(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)

    searches = [client.get("/search?q=python", headers=ALICE_HEADERS).status_code for _ in range(3)]

    assert searches == [200, 200, 429]
    assert client.get("/profiles", headers=ALICE_HEADERS).status_code == 200


def test_callers_without_a_valid_credential_share_the_budget_of_their_address(
    clean_db: Engine,
) -> None:
    client, _ = limited_client(clean_db)

    codes = [client.get("/profiles", headers=bearer(f"bad-{n}")).status_code for n in range(4)]

    assert codes == [401, 401, 401, 429]


def test_public_search_is_limited_by_address(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)

    codes = [client.get("/search?q=python").status_code for _ in range(3)]

    assert codes == [200, 200, 429]


def test_event_streams_are_not_counted(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)
    headers = {**ALICE_HEADERS, "Accept": "text/event-stream"}

    codes = [client.get("/profiles", headers=headers).status_code for _ in range(6)]

    assert codes == [200] * 6
    assert client.get("/profiles", headers=ALICE_HEADERS).headers["x-ratelimit-remaining"] == "2"


def test_a_forged_forwarded_for_does_not_help_without_a_trusted_proxy(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db)

    codes = [
        client.get("/profiles", headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code
        for n in range(4)
    ]

    assert codes == [401, 401, 401, 429]


def test_a_trusted_proxy_hop_picks_the_address_it_appended(clean_db: Engine) -> None:
    client, _ = limited_client(clean_db, trusted_proxy_hops=1)

    def call(forwarded: str) -> int:
        return client.get("/profiles", headers={"X-Forwarded-For": forwarded}).status_code

    for _ in range(3):
        call("6.6.6.6, 1.1.1.1")  # the forged first entry changes nothing: 1.1.1.1 is counted

    assert call("7.7.7.7, 1.1.1.1") == 429
    assert call("7.7.7.7, 2.2.2.2") == 401


def test_limiting_can_be_turned_off(clean_db: Engine) -> None:
    app = create_app(
        settings(rate_limit_enabled=False, rate_limit_default_requests=1),
        clean_db,
        FakeEmbeddingClient(),
    )
    open_client = TestClient(app)

    codes = [open_client.get("/profiles", headers=ALICE_HEADERS).status_code for _ in range(5)]

    assert codes == [200] * 5
    assert "x-ratelimit-limit" not in open_client.get("/profiles", headers=ALICE_HEADERS).headers
