"""The error envelope, request ids and the access log, through the real app."""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.api import create_app
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.observability.logs import JsonFormatter
from tests.auth_helpers import ALICE_HEADERS, auth_client, bearer, settings, token
from tests.test_api_profiles import BODY

ENVELOPE_KEYS = {"code", "message", "request_id"}


def error_of(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    assert list(body) == ["error"]
    error: dict[str, Any] = body["error"]
    assert ENVELOPE_KEYS <= set(error)
    return error


# --- one envelope for every failure -------------------------------------------------------


def test_http_errors_use_the_envelope_with_the_request_id(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    response = client.get("/profiles/999999", headers=ALICE_HEADERS)

    error = error_of(response)
    assert (response.status_code, error["code"], error["message"]) == (
        404,
        "not_found",
        "profile not found",
    )
    assert error["request_id"] == response.headers["x-request-id"]


def test_unknown_routes_and_methods_use_it_too(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    missing = client.get("/nope", headers=ALICE_HEADERS)
    wrong_method = client.patch("/search", headers=ALICE_HEADERS)

    assert (missing.status_code, error_of(missing)["code"]) == (404, "not_found")
    assert (wrong_method.status_code, error_of(wrong_method)["code"]) == (405, "method_not_allowed")


def test_authentication_errors_keep_their_headers(clean_db: Engine) -> None:
    response = auth_client(clean_db).get("/profiles")

    assert (response.status_code, error_of(response)["code"]) == (401, "unauthenticated")
    assert response.headers["www-authenticate"] == "Bearer"


def test_validation_errors_list_the_problems_without_the_submitted_values(
    clean_db: Engine,
) -> None:
    secret_value = "do-not-echo-this-value"
    client = auth_client(clean_db)

    response = client.post(
        "/profiles", json={**BODY, "name": "", "unknown": secret_value}, headers=ALICE_HEADERS
    )

    error = error_of(response)
    assert (response.status_code, error["code"]) == (422, "validation_error")
    assert error["details"] and all({"loc", "msg", "type"} == set(d) for d in error["details"])
    assert secret_value not in response.text


def test_a_conflict_uses_the_envelope(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    client.post("/profiles", json=BODY, headers=ALICE_HEADERS)

    response = client.post(
        "/profiles", json={**BODY, "summary": "different"}, headers=ALICE_HEADERS
    )

    assert (response.status_code, error_of(response)["code"]) == (409, "conflict")


def test_a_service_validation_failure_becomes_details(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    created = client.post("/profiles", json=BODY, headers=ALICE_HEADERS).json()

    response = client.patch(
        f"/profiles/{created['id']}",
        json={"desired_titles": [], "required_skills": [], "summary": ""},
        headers=ALICE_HEADERS,
    )

    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_the_success_schemas_are_unchanged(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    created = client.post("/profiles", json=BODY, headers=ALICE_HEADERS)

    assert created.status_code == 201
    assert "error" not in created.json() and created.json()["name"] == "Backend"


# --- unhandled exceptions -----------------------------------------------------------------


def failing_client(clean_db: Engine) -> TestClient:
    app = create_app(settings(), clean_db, FakeEmbeddingClient())

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("connection string postgresql://u:topsecret@db/x leaked")

    return TestClient(app, raise_server_exceptions=False)


def test_an_unhandled_exception_is_a_generic_500_with_the_request_id(clean_db: Engine) -> None:
    response = failing_client(clean_db).get("/boom", headers={"X-Request-ID": "trace-0001-abc"})

    error = error_of(response)
    assert response.status_code == 500
    assert (error["code"], error["message"]) == ("internal_error", "internal server error")
    assert error["request_id"] == "trace-0001-abc" == response.headers["x-request-id"]
    assert "topsecret" not in response.text and "RuntimeError" not in response.text


def test_an_unhandled_exception_is_logged_with_its_traceback_and_redacted(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    failing_client(clean_db).get("/boom")

    entries = [r for r in caplog.records if r.name == "sanket.api.middleware"]
    assert entries and entries[0].exc_info is not None
    assert "topsecret" not in JsonFormatter().format(entries[0])


# --- request ids ------------------------------------------------------------------------


def test_a_request_id_is_generated_and_a_safe_one_is_kept(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    generated = client.get("/profiles", headers=ALICE_HEADERS)
    kept = client.get("/profiles", headers={**ALICE_HEADERS, "X-Request-ID": "client-id-12345"})
    unsafe = client.get("/profiles", headers={**ALICE_HEADERS, "X-Request-ID": "bad id\t;drop"})

    assert len(generated.headers["x-request-id"]) == 32
    assert kept.headers["x-request-id"] == "client-id-12345"
    assert unsafe.headers["x-request-id"] != "bad id\t;drop"
    assert len(unsafe.headers["x-request-id"]) == 32


# --- the access log -----------------------------------------------------------------------


def access_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    formatter = JsonFormatter()
    return [json.loads(formatter.format(r)) for r in caplog.records if r.name == "sanket.access"]


def test_one_access_line_per_request_without_the_query_string(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    client = auth_client(clean_db)

    client.get("/profiles/12?stream_token=v1.secretpart.sig&x=1", headers=ALICE_HEADERS)

    [line] = access_lines(caplog)
    assert (line["http_method"], line["http_path"], line["http_status"]) == (
        "GET",
        "/profiles/12",
        404,
    )
    assert line["duration_ms"] >= 0 and line["request_id"]
    assert "secretpart" not in json.dumps(line)


def test_the_bearer_token_never_reaches_the_logs(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    value = token(sub="alice")

    auth_client(clean_db).get("/profiles", headers=bearer(value))
    auth_client(clean_db).get("/profiles", headers=bearer(value[:-3] + "xyz"))

    formatter = JsonFormatter()
    assert all(value[:20] not in formatter.format(r) for r in caplog.records)
