"""Accounts through the API: sign-up, log-in, public browsing and isolation between accounts."""

from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from sanket.accounts.passwords import verify_password
from sanket.api import create_app
from sanket.embeddings.fake import FakeEmbeddingClient
from tests.auth_helpers import API_KEY, SECRET, auth_client, bearer, settings
from tests.search_helpers import add_search_job, extraction_data
from tests.test_api_profiles import BODY, seed_matches

PASSWORD = "correct horse battery staple"
ADA = "ada@example.com"
BOB = "bob@example.com"


def sign_up(client: TestClient, email: str = ADA, password: str = PASSWORD) -> Any:
    return client.post("/auth/signup", json={"email": email, "password": password})


def log_in(client: TestClient, email: str = ADA, password: str = PASSWORD) -> Any:
    return client.post("/auth/login", json={"email": email, "password": password})


def headers_of(response: Any) -> dict[str, str]:
    assert response.status_code in (200, 201), response.text
    return bearer(response.json()["access_token"])


def claims_of(response: Any) -> dict[str, Any]:
    return jwt.decode(response.json()["access_token"], SECRET, algorithms=["HS256"])


def scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one_or_none()


# --- sign-up ------------------------------------------------------------------------------


def test_signing_up_creates_an_account_and_signs_it_in(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    response = sign_up(client, " Ada@Example.COM ")

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["email"] == ADA
    assert body["expires_in"] == 3600
    assert response.headers["cache-control"] == "no-store"
    user_id = scalar(clean_db, "select id from users where email = :e", e=ADA)
    assert claims_of(response)["sub"] == f"user:{user_id}"
    assert client.get("/profiles", headers=headers_of(response)).status_code == 200


def test_the_password_is_stored_only_as_an_argon2id_hash(clean_db: Engine) -> None:
    sign_up(auth_client(clean_db))

    stored = scalar(clean_db, "select password_hash from users where email = :e", e=ADA)

    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored
    assert verify_password(stored, PASSWORD)


def test_a_second_sign_up_with_the_same_email_is_409_in_any_case(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    assert sign_up(client).status_code == 201

    repeated = [
        sign_up(client),
        sign_up(client, "ADA@example.com", "another password, long enough"),
    ]

    assert [r.status_code for r in repeated] == [409, 409]
    assert all(PASSWORD not in r.text and "another password" not in r.text for r in repeated)
    assert scalar(clean_db, "select count(*) from users") == 1


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": ADA, "password": "short"},
        {"email": ADA, "password": "x" * 129},
        {"email": ADA},
        {"password": PASSWORD},
        {"email": ADA, "password": PASSWORD, "is_admin": True},
        {"email": ["ada@example.com"], "password": PASSWORD},
    ],
    ids=[
        "bad-email",
        "short-password",
        "long-password",
        "no-password",
        "no-email",
        "extra",
        "list",
    ],
)
def test_invalid_sign_up_bodies_are_422_and_create_nothing(
    clean_db: Engine, body: dict[str, Any]
) -> None:
    response = auth_client(clean_db).post("/auth/signup", json=body)

    assert response.status_code == 422
    assert scalar(clean_db, "select count(*) from users") == 0


def test_a_rejected_password_is_not_echoed_back(clean_db: Engine) -> None:
    rejected = "private-pw"

    response = auth_client(clean_db).post("/auth/signup", json={"email": ADA, "password": rejected})

    assert response.status_code == 422
    assert rejected not in response.text


def test_a_body_that_is_not_json_is_422(clean_db: Engine) -> None:
    response = auth_client(clean_db).post("/auth/signup", content=b"email=a&password=b")

    assert response.status_code == 422


def test_accounts_are_off_without_a_signing_secret(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_jwt_secret=None, auth_api_keys=f"svc={API_KEY}")

    assert sign_up(client).status_code == 404
    assert log_in(client).status_code == 404
    assert scalar(clean_db, "select count(*) from users") == 0


# --- log-in -------------------------------------------------------------------------------


def test_logging_in_returns_a_token_for_the_same_account(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    signed_up = sign_up(client)

    logged_in = log_in(client, "  ADA@example.com")

    assert logged_in.status_code == 200
    assert logged_in.headers["cache-control"] == "no-store"
    assert claims_of(logged_in)["sub"] == claims_of(signed_up)["sub"]
    assert client.get("/profiles", headers=headers_of(logged_in)).status_code == 200


def test_a_wrong_password_and_an_unknown_email_get_the_same_401(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    sign_up(client)

    wrong_password = log_in(client, ADA, "not the right password")
    unknown_email = log_in(client, "nobody@example.com", PASSWORD)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.headers["www-authenticate"] == "Bearer"
    assert "not the right password" not in wrong_password.text


def test_a_short_wrong_password_at_log_in_is_401_not_422(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    sign_up(client)

    assert log_in(client, ADA, "x").status_code == 401


def test_a_sign_up_token_works_when_scope_issuer_and_audience_are_required(
    clean_db: Engine,
) -> None:
    client = auth_client(
        clean_db, auth_issuer="sanket", auth_audience="web", auth_required_scope="sanket"
    )

    signed_up = sign_up(client)

    assert client.get("/profiles", headers=headers_of(signed_up)).status_code == 200
    assert client.get("/profiles", headers=headers_of(log_in(client))).status_code == 200


# --- rate limits --------------------------------------------------------------------------


def test_sign_up_and_log_in_are_limited_per_client_address(clean_db: Engine) -> None:
    client = auth_client(clean_db, rate_limit_auth_requests=3, rate_limit_auth_email_requests=50)

    codes = [log_in(client, f"user{n}@example.com").status_code for n in range(4)]
    blocked = log_in(client, "another@example.com")

    assert codes == [401, 401, 401, 429]
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert sign_up(client, "fresh@example.com").status_code == 429


def test_log_in_is_limited_per_email_whatever_its_spelling(clean_db: Engine) -> None:
    client = auth_client(clean_db, rate_limit_auth_requests=50, rate_limit_auth_email_requests=2)

    spellings = [ADA, " ADA@example.com", "Ada@Example.com"]
    codes = [log_in(client, email, "wrong password!!").status_code for email in spellings]

    assert codes == [401, 401, 429]
    assert log_in(client, BOB, "wrong password!!").status_code == 401


def test_the_auth_limits_apply_even_when_general_rate_limiting_is_off(clean_db: Engine) -> None:
    client = auth_client(clean_db, rate_limit_enabled=False, rate_limit_auth_requests=2)

    codes = [log_in(client, f"user{n}@example.com").status_code for n in range(3)]

    assert codes == [401, 401, 429]


def test_a_limited_sign_up_does_not_create_an_account(clean_db: Engine) -> None:
    client = auth_client(clean_db, rate_limit_auth_requests=1)
    log_in(client)

    assert sign_up(client).status_code == 429
    assert scalar(clean_db, "select count(*) from users") == 0


# --- public browsing ----------------------------------------------------------------------


def test_jobs_and_search_need_no_credential(clean_db: Engine) -> None:
    job_id = add_search_job(clean_db, title="Python Developer", extraction=extraction_data())
    client = auth_client(clean_db)

    assert client.get("/jobs").status_code == 200
    assert client.get(f"/jobs/{job_id}").status_code == 200
    assert client.get("/search", params={"q": "python"}).status_code == 200


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/profiles"),
        ("POST", "/profiles"),
        ("GET", "/profiles/1/matches"),
        ("GET", "/saved-jobs"),
        ("PUT", "/saved-jobs/1"),
        ("DELETE", "/saved-jobs/1"),
        ("POST", "/auth/stream-token"),
    ],
)
def test_everything_owned_still_needs_a_credential(clean_db: Engine, method: str, url: str) -> None:
    response = auth_client(clean_db).request(method, url, json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# --- isolation and linking ----------------------------------------------------------------


def test_one_account_cannot_see_or_change_another_accounts_data(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client, ADA))
    bob = headers_of(sign_up(client, BOB))
    job_id = add_search_job(clean_db, extraction=extraction_data())
    profile_id = client.post("/profiles", json=BODY, headers=ada).json()["id"]
    seed_matches(clean_db, profile_id, 2)
    assert client.put(f"/saved-jobs/{job_id}", headers=ada).status_code == 200
    url = f"/profiles/{profile_id}"

    responses = [
        client.get(url, headers=bob),
        client.put(url, json=BODY, headers=bob),
        client.patch(url, json={"summary": "x"}, headers=bob),
        client.delete(url, headers=bob),
        client.get(f"{url}/matches", headers=bob),
        client.post("/auth/stream-token", json={"profile_id": profile_id}, headers=bob),
    ]

    assert [r.status_code for r in responses] == [404] * 6
    assert client.get("/profiles", headers=bob).json()["items"] == []
    assert client.get("/saved-jobs", headers=bob).json()["items"] == []
    assert client.delete(f"/saved-jobs/{job_id}", headers=bob).status_code == 204
    assert len(client.get(f"{url}/matches", headers=ada).json()["items"]) == 2
    assert [s["job_id"] for s in client.get("/saved-jobs", headers=ada).json()["items"]] == [job_id]


def test_rows_made_by_an_account_are_linked_to_it(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client, ADA))
    job_id = add_search_job(clean_db, extraction=extraction_data())
    client.post("/profiles", json=BODY, headers=ada)
    client.put(f"/saved-jobs/{job_id}", headers=ada)

    user_id = scalar(clean_db, "select id from users where email = :e", e=ADA)

    assert scalar(clean_db, "select user_id from profile") == user_id
    assert scalar(clean_db, "select owner_id from profile") == f"user:{user_id}"
    assert scalar(clean_db, "select user_id from saved_job") == user_id


def test_rows_of_a_static_key_have_no_account(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")
    job_id = add_search_job(clean_db, extraction=extraction_data())

    assert client.post("/profiles", json=BODY, headers=bearer(API_KEY)).status_code == 201
    assert client.put(f"/saved-jobs/{job_id}", headers=bearer(API_KEY)).status_code == 200

    assert scalar(clean_db, "select owner_id from profile") == "svc"
    assert scalar(clean_db, "select user_id from profile") is None
    assert scalar(clean_db, "select user_id from saved_job") is None


def test_a_token_of_a_deleted_account_cannot_create_rows(clean_db: Engine) -> None:
    app = create_app(settings(), clean_db, FakeEmbeddingClient())
    client = TestClient(app, raise_server_exceptions=False)
    ada = headers_of(sign_up(client, ADA))
    job_id = add_search_job(clean_db, extraction=extraction_data())
    with clean_db.begin() as conn:
        conn.execute(text("delete from users"))

    created = client.post("/profiles", json=BODY, headers=ada)
    saved = client.put(f"/saved-jobs/{job_id}", headers=ada)

    assert (created.status_code, saved.status_code) == (401, 401)


def test_deleting_an_account_deletes_what_it_owns(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client, ADA))
    bob = headers_of(sign_up(client, BOB))
    job_id = add_search_job(clean_db, extraction=extraction_data())
    for headers in (ada, bob):
        client.post("/profiles", json=BODY, headers=headers)
        client.put(f"/saved-jobs/{job_id}", headers=headers)

    with clean_db.begin() as conn:
        conn.execute(text("delete from users where email = :e"), {"e": ADA})

    assert [p["name"] for p in client.get("/profiles", headers=bob).json()["items"]] == ["Backend"]
    assert scalar(clean_db, "select count(*) from profile") == 1
    assert scalar(clean_db, "select count(*) from saved_job") == 1
