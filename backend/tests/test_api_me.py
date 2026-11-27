"""`GET /me` (who the account is, named by its career profile) and the note that explains a
profile that is not ready."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from sanket.api.profile_schemas import embedding_note_of
from tests.auth_helpers import API_KEY, auth_client, bearer
from tests.test_api_accounts import BOB, headers_of, sign_up
from tests.test_api_profiles import BODY


def set_personal(client: TestClient, headers: dict[str, str], **fields: Any) -> Any:
    return client.put("/career/personal", json=fields, headers=headers)


# --- /me -----------------------------------------------------------------------------------


def test_a_new_account_has_its_email_and_no_name(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    response = client.get("/me", headers=ada)

    assert response.status_code == 200
    assert response.json() == {"email": "ada@example.com", "full_name": "", "headline": ""}


def test_the_name_and_headline_come_from_the_career_profile(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    set_personal(client, ada, full_name="  Ada   Example ", headline="Backend engineer")

    assert client.get("/me", headers=ada).json() == {
        "email": "ada@example.com",
        "full_name": "Ada Example",
        "headline": "Backend engineer",
    }


def test_each_account_sees_only_its_own_name(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    bob = headers_of(sign_up(client, BOB))
    set_personal(client, ada, full_name="Ada Example")

    assert client.get("/me", headers=bob).json()["full_name"] == ""
    set_personal(client, bob, full_name="Bob Example")
    assert client.get("/me", headers=ada).json()["full_name"] == "Ada Example"


def test_the_name_survives_signing_in_again(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    set_personal(client, headers_of(sign_up(client)), full_name="Ada Example")

    login = client.post(
        "/auth/login", json={"email": "ada@example.com", "password": "correct horse battery staple"}
    )

    assert client.get("/me", headers=headers_of(login)).json()["full_name"] == "Ada Example"


def test_the_name_can_no_longer_be_written_through_me(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    response = client.put("/me", json={"full_name": "Ada Example"}, headers=ada)

    assert response.status_code == 405


def test_me_needs_a_credential(clean_db: Engine) -> None:
    assert auth_client(clean_db).get("/me").status_code == 401


def test_a_credential_that_is_not_an_account_has_no_me(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")

    assert client.get("/me", headers=bearer(API_KEY)).status_code == 404


def test_a_token_of_a_deleted_account_has_no_me(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    with clean_db.begin() as conn:
        conn.execute(text("delete from users"))

    assert client.get("/me", headers=ada).status_code == 404


# --- why a profile is not ready -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error", "note"),
    [
        ("ready", None, None),
        ("ready", "ClientError: 429 RESOURCE_EXHAUSTED", None),
        ("pending", None, None),
        ("pending", "", None),
        ("pending", "ClientError: 429 RESOURCE_EXHAUSTED. quota exceeded", "quota"),
        ("pending", "Rate limit reached for requests", "quota"),
        ("failed", "You exceeded your current quota", "quota"),
        ("pending", "ServerError: 503 UNAVAILABLE", "error"),
        ("failed", "ConnectError: connection refused", "error"),
    ],
)
def test_the_note_names_a_quota_failure_and_any_other_failure(
    status: str, error: str | None, note: str | None
) -> None:
    assert embedding_note_of(status, error) == note


def test_a_profile_waiting_on_the_quota_says_so_without_the_provider_text(
    clean_db: Engine,
) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    profile_id = client.post("/profiles", json=BODY, headers=ada).json()["id"]
    assert client.get(f"/profiles/{profile_id}", headers=ada).json()["embedding_note"] is None
    detail = "ClientError: 429 RESOURCE_EXHAUSTED. Quota exceeded for project 123456"
    with clean_db.begin() as conn:
        conn.execute(
            text("update profile set embedding_status = 'pending', embedding_error = :e"),
            {"e": detail},
        )

    response = client.get(f"/profiles/{profile_id}", headers=ada)

    assert response.json()["embedding_status"] == "pending"
    assert response.json()["embedding_note"] == "quota"
    assert "123456" not in response.text
    assert "RESOURCE_EXHAUSTED" not in response.text
    listed = client.get("/profiles", headers=ada).json()["items"][0]
    assert listed["embedding_note"] == "quota"
