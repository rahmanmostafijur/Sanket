"""Personal info (`/me`) and the note that explains a profile that is not ready."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from sanket.accounts.personal import (
    MAX_FULL_NAME_CHARS,
    MAX_HEADLINE_CHARS,
    MAX_LOCATION_CHARS,
    MAX_PERSONAL_SUMMARY_CHARS,
)
from sanket.api.profile_schemas import embedding_note_of
from tests.auth_helpers import API_KEY, auth_client, bearer
from tests.test_api_accounts import BOB, headers_of, scalar, sign_up
from tests.test_api_profiles import BODY

ADA_INFO = {
    "full_name": "Ada Example",
    "headline": "Backend engineer",
    "location": "Berlin, Germany",
    "summary": "Builds APIs and data pipelines.",
}


def put_me(client: TestClient, headers: dict[str, str], **fields: Any) -> Any:
    return client.put("/me", json={**ADA_INFO, **fields}, headers=headers)


# --- read and write -----------------------------------------------------------------------


def test_a_new_account_has_the_email_and_no_personal_info(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    response = client.get("/me", headers=ada)

    assert response.status_code == 200
    assert response.json() == {
        "email": "ada@example.com",
        "full_name": "",
        "headline": "",
        "location": "",
        "summary": "",
    }


def test_personal_info_is_saved_and_read_back(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    saved = put_me(client, ada)

    assert saved.status_code == 200
    assert saved.json() == {"email": "ada@example.com", **ADA_INFO}
    assert client.get("/me", headers=ada).json() == saved.json()
    assert scalar(clean_db, "select full_name from users") == "Ada Example"


def test_text_is_trimmed_and_whitespace_collapsed(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    saved = put_me(client, ada, full_name="  Ada \n  Example ", headline="\tBackend   engineer")

    assert saved.json()["full_name"] == "Ada Example"
    assert saved.json()["headline"] == "Backend engineer"


def test_putting_replaces_all_four_and_an_empty_value_clears_one(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    put_me(client, ada)

    cleared = client.put("/me", json={"full_name": "Ada Example"}, headers=ada)

    assert cleared.status_code == 200
    assert cleared.json()["headline"] == ""
    assert scalar(clean_db, "select headline from users") is None
    assert scalar(clean_db, "select full_name from users") == "Ada Example"


def test_the_largest_allowed_values_are_accepted(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))

    response = put_me(
        client,
        ada,
        full_name="n" * MAX_FULL_NAME_CHARS,
        headline="h" * MAX_HEADLINE_CHARS,
        location="l" * MAX_LOCATION_CHARS,
        summary="s" * MAX_PERSONAL_SUMMARY_CHARS,
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"full_name": "n" * (MAX_FULL_NAME_CHARS + 1)},
        {"headline": "h" * (MAX_HEADLINE_CHARS + 1)},
        {"location": "l" * (MAX_LOCATION_CHARS + 1)},
        {"summary": "s" * (MAX_PERSONAL_SUMMARY_CHARS + 1)},
        {"full_name": "Ada\x00Example"},
        {"full_name": 42},
        {"full_name": None},
        {"is_admin": True},
    ],
    ids=["name", "headline", "location", "summary", "nul", "number", "null", "extra"],
)
def test_invalid_personal_info_is_422_and_changes_nothing(
    clean_db: Engine, changes: dict[str, Any]
) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    put_me(client, ada)

    response = put_me(client, ada, **changes)

    assert response.status_code == 422
    assert client.get("/me", headers=ada).json() == {"email": "ada@example.com", **ADA_INFO}


# --- who may use it -----------------------------------------------------------------------


def test_each_account_sees_and_changes_only_its_own_info(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    bob = headers_of(sign_up(client, BOB))
    put_me(client, ada)

    assert client.get("/me", headers=bob).json()["full_name"] == ""
    put_me(client, bob, full_name="Bob Example")
    assert client.get("/me", headers=ada).json()["full_name"] == "Ada Example"


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_me_needs_a_credential(clean_db: Engine, method: str) -> None:
    response = auth_client(clean_db).request(method, "/me", json=ADA_INFO)

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_a_credential_that_is_not_an_account_has_no_me(clean_db: Engine, method: str) -> None:
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")

    response = client.request(method, "/me", json=ADA_INFO, headers=bearer(API_KEY))

    assert response.status_code == 404


def test_a_token_of_a_deleted_account_has_no_me(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = headers_of(sign_up(client))
    with clean_db.begin() as conn:
        conn.execute(text("delete from users"))

    assert client.get("/me", headers=ada).status_code == 404
    assert put_me(client, ada).status_code == 404


def test_personal_info_survives_signing_in_again(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    put_me(client, headers_of(sign_up(client)))

    login = client.post(
        "/auth/login", json={"email": "ada@example.com", "password": "correct horse battery staple"}
    )

    assert client.get("/me", headers=headers_of(login)).json()["full_name"] == "Ada Example"


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
