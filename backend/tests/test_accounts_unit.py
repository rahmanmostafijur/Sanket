"""Account building blocks: passwords, email rules, owner ids, access tokens, key names."""

import uuid

import jwt
import pytest
from pydantic import ValidationError

from sanket.accounts.identity import USER_OWNER_PREFIX, owner_id_for, user_id_of
from sanket.accounts.passwords import hash_password, verify_password
from sanket.accounts.rules import (
    MAX_EMAIL_LENGTH,
    is_valid_email,
    normalize_email,
)
from sanket.accounts.tokens import AccessTokens, access_tokens_from_settings
from sanket.auth.keys import parse_api_keys
from sanket.runtime_checks import ConfigError, check_api
from tests.auth_helpers import API_KEY, SECRET, settings

PASSWORD = "correct horse battery staple"


# --- passwords ----------------------------------------------------------------------------


def test_a_password_is_hashed_with_argon2id_and_verifies_only_itself() -> None:
    stored = hash_password(PASSWORD)

    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored
    assert verify_password(stored, PASSWORD)
    assert not verify_password(stored, PASSWORD + "x")


def test_the_same_password_gets_a_different_hash_each_time() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


@pytest.mark.parametrize("stored", [None, "", "not-a-hash", "$argon2id$garbage"])
def test_a_missing_or_malformed_stored_hash_never_matches(stored: str | None) -> None:
    assert not verify_password(stored, PASSWORD)


# --- email rules --------------------------------------------------------------------------


def test_an_email_is_trimmed_and_lower_cased() -> None:
    assert normalize_email("  Ada.Lovelace@Example.COM ") == "ada.lovelace@example.com"


@pytest.mark.parametrize("email", ["ada@example.com", "a.b+tag@mail.example.co.uk", "x@y.z"])
def test_ordinary_addresses_are_valid(email: str) -> None:
    assert is_valid_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "",
        "ada",
        "ada@",
        "@example.com",
        "ada@example",
        "ada@@example.com",
        "ada lovelace@example.com",
        "ada@exa mple.com",
        "ada@example..com",
        "ada@.example.com",
        "ada\n@example.com",
        "a" * 65 + "@example.com",
        "a@" + "b" * MAX_EMAIL_LENGTH + ".com",
    ],
)
def test_what_cannot_be_an_address_is_invalid(email: str) -> None:
    assert not is_valid_email(email)


# --- owner ids ----------------------------------------------------------------------------


def test_an_account_maps_to_a_user_owner_id_and_back() -> None:
    user_id = uuid.uuid4()

    owner = owner_id_for(user_id)

    assert owner == f"{USER_OWNER_PREFIX}{user_id}"
    assert user_id_of(owner) == user_id


@pytest.mark.parametrize("owner", ["alice", "svc", "default", "user:", "user:not-a-uuid", "User:x"])
def test_owners_that_are_not_accounts_have_no_user_id(owner: str) -> None:
    assert user_id_of(owner) is None


# --- access tokens ------------------------------------------------------------------------


def decode(token: str, **kwargs: object) -> dict[str, object]:
    return jwt.decode(token, SECRET, algorithms=["HS256"], **kwargs)  # type: ignore[arg-type]


def test_a_token_carries_the_owner_id_email_and_expiry() -> None:
    user_id = uuid.uuid4()
    tokens = AccessTokens(secret=SECRET, ttl_seconds=600)

    issued = tokens.issue(user_id, "ada@example.com", now=1_000_000)
    claims = decode(issued.token, options={"verify_exp": False})

    assert issued.expires_in == 600
    assert claims == {
        "sub": f"user:{user_id}",
        "email": "ada@example.com",
        "iat": 1_000_000,
        "exp": 1_000_600,
    }


def test_a_token_carries_the_issuer_audience_and_scope_when_configured() -> None:
    tokens = AccessTokens(
        secret=SECRET,
        ttl_seconds=600,
        owner_claim="uid",
        issuer="sanket",
        audience="web",
        scope="sanket",
    )

    claims = decode(
        tokens.issue(uuid.uuid4(), "ada@example.com").token, audience="web", issuer="sanket"
    )

    assert claims["iss"] == "sanket"
    assert claims["aud"] == "web"
    assert claims["scope"] == "sanket"
    assert "sub" not in claims
    assert str(claims["uid"]).startswith(USER_OWNER_PREFIX)


def test_tokens_are_built_from_settings_only_with_a_signing_secret() -> None:
    assert access_tokens_from_settings(settings(auth_jwt_secret=None, auth_dev_bypass=True)) is None

    tokens = access_tokens_from_settings(settings(auth_access_token_ttl_seconds=900))

    assert tokens is not None
    assert tokens.ttl_seconds == 900


@pytest.mark.parametrize("ttl", [0, 299, 86401])
def test_a_token_lifetime_outside_five_minutes_to_a_day_is_refused(ttl: int) -> None:
    with pytest.raises(ValidationError):
        settings(auth_access_token_ttl_seconds=ttl)


# --- the reserved owner prefix ------------------------------------------------------------


def test_a_static_key_cannot_be_named_as_an_account() -> None:
    _, problems = parse_api_keys(f"{owner_id_for(uuid.uuid4())}={API_KEY}")

    assert len(problems) == 1
    assert "reserved for accounts" in problems[0]
    assert API_KEY not in problems[0]


def test_the_startup_check_refuses_a_key_named_as_an_account() -> None:
    config = settings(auth_api_keys=f"{owner_id_for(uuid.uuid4())}={API_KEY}")

    with pytest.raises(ConfigError, match="reserved for accounts"):
        check_api(config)
