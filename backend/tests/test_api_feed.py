"""The live match feed endpoint through FastAPI's test client.

The test client collects a whole response, so these streams are made to end by themselves
(FEED_MAX_STREAM_SECONDS is a fraction of a second). The live behaviour is in test_feed_stream.
"""

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.api import create_app
from sanket.api.deps import ApiContext
from sanket.config import Settings
from sanket.embeddings.fake import FakeEmbeddingClient
from tests.feed_helpers import FakeRedisSide, fields_of, ids_of
from tests.index_helpers import SPEC
from tests.match_helpers import OWNER, add_profile, seed_job
from tests.test_profile_schema import add_match

URL_FORMAT = "/profiles/{}/matches/stream"


def feed_client(
    engine: Engine, owner: str = OWNER, redis: FakeRedisSide | None = None, **settings: Any
) -> TestClient:
    values: dict[str, Any] = {
        "auth_dev_bypass": True,
        "feed_max_stream_seconds": 0.2,
        "feed_heartbeat_seconds": 0.05,
        "feed_db_poll_seconds": 0.02,
        **settings,
    }
    config = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        embedding_model=SPEC.model_name,
        embedding_model_version=SPEC.model_version,
        embedding_dimensions=SPEC.dimensions,
        default_owner_id=owner,
        **values,
    )
    app = create_app(
        config,
        engine,
        FakeEmbeddingClient(),
        task_queue=None,
        feed_redis=redis.factory if redis else None,
    )
    return TestClient(app)


def seed_matches(engine: Engine, count: int, **profile: Any) -> tuple[int, list[int]]:
    profile_id = add_profile(engine, embed=False, **profile).id
    jobs = [seed_job(engine, title=f"Engineer {n}", company=f"Co {n}") for n in range(count)]
    return profile_id, [add_match(engine, profile_id, job_id) for job_id in jobs]


def context_of(client: TestClient) -> ApiContext:
    context: ApiContext = client.app.state.context  # type: ignore[attr-defined]
    return context


def events_of(text: str) -> list[dict[str, str]]:
    return [fields_of(block) for block in text.split("\n\n") if block.startswith("id:")]


# --- what the stream sends ----------------------------------------------------------------


def test_the_stream_sends_the_matches_after_last_event_id_with_the_job_summary(
    clean_db: Engine,
) -> None:
    profile_id, ids = seed_matches(clean_db, 3)
    client = feed_client(clean_db)

    response = client.get(URL_FORMAT.format(profile_id), headers={"Last-Event-ID": str(ids[0])})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [e for e in events_of(response.text) if "event" in e]
    assert [int(e["id"]) for e in events] == ids[1:]
    listed = client.get(f"/profiles/{profile_id}/matches").json()["items"]
    expected = {item["id"]: item for item in listed}
    for event in events:
        assert event["event"] == "match"
        data = json.loads(event["data"])
        assert data.pop("reactivated") is False
        assert data == json.loads(json.dumps(expected[int(event["id"])]))
    assert json.loads(events[0]["data"])["job"]["title"] == "Engineer 1"


def test_the_stream_opens_with_a_retry_hint_and_sets_the_headers_proxies_need(
    clean_db: Engine,
) -> None:
    profile_id, _ = seed_matches(clean_db, 0)
    client = feed_client(clean_db, feed_retry_ms=1500)

    response = client.get(URL_FORMAT.format(profile_id))

    assert response.text.startswith("retry: 1500\n\n")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["connection"] == "keep-alive"
    assert ": ping\n\n" in response.text


def test_the_query_parameter_resumes_when_there_is_no_header(clean_db: Engine) -> None:
    profile_id, ids = seed_matches(clean_db, 3)
    client = feed_client(clean_db)

    response = client.get(URL_FORMAT.format(profile_id), params={"last_event_id": ids[1]})

    assert ids_of([block + "\n\n" for block in response.text.split("\n\n")]) == [ids[2]]


def test_the_header_wins_over_the_query_parameter(clean_db: Engine) -> None:
    profile_id, ids = seed_matches(clean_db, 3)
    client = feed_client(clean_db)

    response = client.get(
        URL_FORMAT.format(profile_id),
        params={"last_event_id": 0},
        headers={"Last-Event-ID": str(ids[1])},
    )

    assert [int(e["id"]) for e in events_of(response.text) if "event" in e] == [ids[2]]


def test_a_blank_last_event_id_means_a_fresh_client(clean_db: Engine) -> None:
    profile_id, ids = seed_matches(clean_db, 2)
    client = feed_client(clean_db)

    response = client.get(URL_FORMAT.format(profile_id), headers={"Last-Event-ID": " "})

    assert response.status_code == 200
    assert f"id: {ids[-1]}\n\n" in response.text and "event: match" not in response.text


def test_the_stream_works_with_redis_configured_and_also_without(clean_db: Engine) -> None:
    profile_id, ids = seed_matches(clean_db, 2)

    for redis in (FakeRedisSide(), None):
        client = feed_client(clean_db, redis=redis)
        response = client.get(URL_FORMAT.format(profile_id), headers={"Last-Event-ID": "0"})
        assert [int(e["id"]) for e in events_of(response.text) if "event" in e] == ids


# --- who may subscribe --------------------------------------------------------------------


def test_another_owner_cannot_stream_the_profile(clean_db: Engine) -> None:
    profile_id, _ = seed_matches(clean_db, 1)
    stranger = feed_client(clean_db, owner="someone-else")

    response = stranger.get(URL_FORMAT.format(profile_id))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "profile not found"
    assert context_of(stranger).feed_limiter.open_streams == 0


def test_a_stream_of_a_missing_profile_is_a_404_like_a_foreign_one(clean_db: Engine) -> None:
    client = feed_client(clean_db)

    missing = client.get(URL_FORMAT.format(99999))
    assert missing.json()["error"]["message"] == "profile not found"


# --- a bad resume point -------------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "1 2", "0x10", "9223372036854775808", "1;2"])
def test_an_invalid_last_event_id_is_a_400_in_the_header_and_in_the_query(
    clean_db: Engine, value: str
) -> None:
    profile_id, _ = seed_matches(clean_db, 0)
    client = feed_client(clean_db)

    in_query = client.get(URL_FORMAT.format(profile_id), params={"last_event_id": value})
    in_header = client.get(URL_FORMAT.format(profile_id), headers={"Last-Event-ID": value})

    assert in_query.status_code == 400 and in_header.status_code == 400
    assert in_header.json()["error"]["message"] == "invalid Last-Event-ID"
    assert context_of(client).feed_limiter.open_streams == 0


def test_digits_of_other_scripts_are_not_a_match_id(clean_db: Engine) -> None:
    profile_id, _ = seed_matches(clean_db, 0)
    client = feed_client(clean_db)

    response = client.get(URL_FORMAT.format(profile_id), params={"last_event_id": "٣"})

    assert response.status_code == 400


# --- the cap on open streams --------------------------------------------------------------


def test_too_many_streams_of_a_profile_is_a_429_until_one_closes(clean_db: Engine) -> None:
    profile_id, _ = seed_matches(clean_db, 0)
    client = feed_client(clean_db, feed_max_streams_per_profile=1, feed_retry_ms=2500)
    held = context_of(client).feed_limiter.acquire(profile_id)
    assert held is not None

    refused = client.get(URL_FORMAT.format(profile_id))
    held.release()
    accepted = client.get(URL_FORMAT.format(profile_id))

    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "3"
    assert accepted.status_code == 200


def test_the_cap_per_process_applies_across_profiles(clean_db: Engine) -> None:
    first, _ = seed_matches(clean_db, 0, name="first")
    second, _ = seed_matches(clean_db, 0, name="second")
    client = feed_client(clean_db, feed_max_streams=1)
    held = context_of(client).feed_limiter.acquire(first)
    assert held is not None

    assert client.get(URL_FORMAT.format(second)).status_code == 429


def test_a_finished_stream_gives_its_slot_back(clean_db: Engine) -> None:
    profile_id, _ = seed_matches(clean_db, 0)
    client = feed_client(clean_db, feed_max_streams_per_profile=1)

    statuses = [client.get(URL_FORMAT.format(profile_id)).status_code for _ in range(3)]

    assert statuses == [200, 200, 200]
    assert context_of(client).feed_limiter.open_streams == 0


def test_the_stream_is_listed_in_the_openapi_document(clean_db: Engine) -> None:
    client = feed_client(clean_db)

    operation = client.get("/openapi.json").json()["paths"]["/profiles/{profile_id}/matches/stream"]

    assert "text/event-stream" in operation["get"]["responses"]["200"]["content"]
