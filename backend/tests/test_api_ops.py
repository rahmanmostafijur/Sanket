"""Probes and metrics through the real app: liveness, readiness, timeouts, route labels."""

import time
from typing import Any

import fakeredis
import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine, create_engine, text

from sanket.api import create_app
from sanket.api.health import (
    FAILED,
    OK,
    TIMEOUT,
    ReadinessProbe,
    migrations_check,
    redis_check,
)
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.queue.base import QueueHealth
from sanket.queue.memory import InMemoryTaskQueue
from tests.auth_helpers import ALICE_HEADERS, bearer, settings


def dead_engine() -> Engine:
    return create_engine(
        "postgresql+psycopg://u:secretpw@127.0.0.1:1/x_test", connect_args={"connect_timeout": 1}
    )


def client_for(engine: Engine, queue: Any = None, **overrides: Any) -> TestClient:
    config = settings(**overrides)
    return TestClient(create_app(config, engine, FakeEmbeddingClient(), task_queue=queue))


def scrape(client: TestClient, headers: dict[str, str] | None = None) -> str:
    response = client.get("/metrics", headers=headers)
    assert response.status_code == 200, response.text
    return response.text


# --- liveness and readiness ---------------------------------------------------------------


def test_liveness_needs_no_dependency_and_no_credentials() -> None:
    client = client_for(dead_engine())

    response = client.get("/healthz")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert response.headers["x-request-id"]


def test_readiness_is_ready_with_a_working_database(clean_db: Engine) -> None:
    response = client_for(clean_db).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_is_503_without_the_database_and_does_not_leak_the_error() -> None:
    response = client_for(dead_engine()).get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    # A refused connection reports as failed, a slow one (Windows) as timeout.
    assert body["checks"]["database"] in {"failed", "timeout"}
    assert "secretpw" not in response.text and "127.0.0.1" not in response.text


def test_the_probes_are_public_and_not_rate_limited(clean_db: Engine) -> None:
    client = client_for(clean_db, rate_limit_default_requests=1)

    codes = [client.get(path).status_code for path in ("/healthz", "/readyz") * 5]

    assert codes == [200] * 10


def test_the_migration_check_passes_at_head_and_fails_otherwise(clean_db: Engine) -> None:
    ok = client_for(clean_db, readyz_check_migrations=True).get("/readyz")
    memory = sqlalchemy.create_engine("sqlite://")
    with memory.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('not_the_head')"))
    ini = str(settings().alembic_ini_path)

    assert ok.json()["checks"] == {"database": "ok", "migrations": "ok"}
    with pytest.raises(RuntimeError, match="migration head"):
        migrations_check(memory, ini)()


def test_the_redis_check_pings_and_reports_failure() -> None:
    redis_check(fakeredis.FakeRedis())()

    class Down(fakeredis.FakeRedis):
        def ping(self, *args: Any, **kwargs: Any) -> Any:
            raise RedisConnectionError("down")

    with pytest.raises(RedisConnectionError):
        redis_check(Down())()


def test_a_slow_check_times_out_and_a_failing_one_is_reported() -> None:
    def slow() -> None:
        time.sleep(1.0)

    def broken() -> None:
        raise ValueError("boom with secret")

    probe = ReadinessProbe({"fast": lambda: None, "slow": slow, "broken": broken}, 0.1)

    started = time.monotonic()
    result = probe.run()

    assert time.monotonic() - started < 0.9
    assert not result.ready
    assert dict(result.checks) == {"fast": OK, "slow": TIMEOUT, "broken": FAILED}


# --- metrics ------------------------------------------------------------------------------


def test_requests_are_counted_by_route_template_not_raw_path(clean_db: Engine) -> None:
    client = client_for(clean_db)
    for profile_id in (1, 2, 3):
        client.get(f"/profiles/{profile_id}", headers=ALICE_HEADERS)
    client.get("/no/such/path/1")
    client.get("/no/such/path/2")

    body = scrape(client)

    assert (
        'sanket_http_requests_total{method="GET",route="/profiles/{profile_id}",status="404"} 3.0'
        in body
    )
    assert 'route="unmatched",status="404"} 2.0' in body
    assert "/profiles/1" not in body and "/no/such" not in body
    assert (
        'sanket_http_request_duration_seconds_bucket{le="0.5",method="GET",route="/profiles/{profile_id}"}'
        in body
    )


def test_status_codes_of_auth_and_rate_limit_failures_are_visible(clean_db: Engine) -> None:
    client = client_for(clean_db, rate_limit_default_requests=1)
    client.get("/profiles")
    client.get("/profiles")

    body = scrape(client)

    assert 'route="/profiles",status="401"} 1.0' in body
    assert 'route="/profiles",status="429"} 1.0' in body


def test_queue_numbers_are_exported(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()
    queue.enqueue("task", {"a": 1}, key="1")
    queue.enqueue("task", {"a": 2}, key="2")

    body = scrape(client_for(clean_db, queue))

    assert "sanket_queue_up 1.0" in body
    assert "sanket_queue_waiting 2.0" in body
    assert "sanket_queue_dead_letters 0.0" in body


class BrokenQueue:
    def health(self) -> QueueHealth:
        raise RedisConnectionError("down")

    def enqueue(self, *args: Any, **kwargs: Any) -> Any:
        raise RedisConnectionError("down")


def test_an_unreachable_queue_is_reported_down_without_failing_the_scrape(
    clean_db: Engine,
) -> None:
    body = scrape(client_for(clean_db, BrokenQueue()))

    assert "sanket_queue_up 0.0" in body
    assert "sanket_queue_waiting" not in body


def test_without_a_queue_no_queue_metrics_are_exported(clean_db: Engine) -> None:
    assert "sanket_queue" not in scrape(client_for(clean_db))


def test_a_metrics_token_is_required_when_set(clean_db: Engine) -> None:
    client = client_for(clean_db, metrics_token="scrape-token-value")

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=bearer("wrong")).status_code == 401
    assert client.get("/metrics", headers=bearer("scrape-token-value")).status_code == 200
    # A user credential is not the scrape token.
    assert client.get("/metrics", headers=ALICE_HEADERS).status_code == 401


def test_production_without_a_metrics_token_does_not_serve_metrics(clean_db: Engine) -> None:
    production = {"environment": "production", "auth_jwks_url": "https://idp.test/jwks"}

    hidden = client_for(clean_db, **production).get("/metrics")
    served = client_for(clean_db, metrics_token="scrape-token-value", **production).get(
        "/metrics", headers=bearer("scrape-token-value")
    )

    assert hidden.status_code == 404
    assert served.status_code == 200


def test_metrics_can_be_switched_off(clean_db: Engine) -> None:
    assert client_for(clean_db, metrics_enabled=False).get("/metrics").status_code == 404
