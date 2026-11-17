"""The authentication building blocks: API keys, JWT verification, stream tokens, startup checks."""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from sanket.auth.authenticator import Authenticator, authenticator_from_settings
from sanket.auth.errors import ForbiddenError, UnauthenticatedError
from sanket.auth.jwt_verifier import JWKS_ALGORITHMS, JwtSettings, JwtVerifier, SecretKey
from sanket.auth.keys import MIN_API_KEY_LENGTH, parse_api_keys
from sanket.auth.principal import is_valid_owner_id
from sanket.auth.stream_token import StreamTokens, feed_path
from sanket.runtime_checks import ConfigError, check_api
from tests.auth_helpers import API_KEY, SECRET, STREAM_SECRET, settings, token

PATH = feed_path(7)


def verifier(**overrides: Any) -> JwtVerifier:
    return JwtVerifier(SecretKey(SECRET), ("HS256",), JwtSettings(**overrides))


# --- API keys -----------------------------------------------------------------------------


def test_api_keys_map_a_key_to_its_owner() -> None:
    keys, problems = parse_api_keys(f"alice={API_KEY},ops={API_KEY}x")

    assert problems == []
    assert keys.owner_for(API_KEY) == "alice"
    assert keys.owner_for(API_KEY + "x") == "ops"
    assert keys.owner_for("nope") is None


@pytest.mark.parametrize(
    "raw",
    ["nokey", f"=key{'x' * 30}", "alice=short", f"a={API_KEY},b={API_KEY}"],
)
def test_malformed_api_keys_are_reported_without_the_key(raw: str) -> None:
    _, problems = parse_api_keys(raw)

    assert problems
    assert all(API_KEY not in problem for problem in problems)
    assert MIN_API_KEY_LENGTH > 0


def test_owner_ids_must_be_printable_and_bounded() -> None:
    assert is_valid_owner_id("auth0|abc-123")
    assert not is_valid_owner_id("has space")
    assert not is_valid_owner_id("")
    assert not is_valid_owner_id("x" * 201)
    assert not is_valid_owner_id(5)


# --- JWT ----------------------------------------------------------------------------------


def test_a_valid_token_yields_its_subject_as_the_owner() -> None:
    principal = verifier().verify(token(sub="user-42"))

    assert (principal.owner_id, principal.method) == ("user-42", "jwt")


@pytest.mark.parametrize(
    "bad",
    [
        token(exp=int(time.time()) - 3600),
        token(exp=None),
        token(secret="another-secret-of-at-least-32-characters!"),
        token(sub=None),
        token(sub="two words"),
        "not.a.jwt",
    ],
    ids=["expired", "no-exp", "wrong-signature", "no-subject", "bad-subject", "garbage"],
)
def test_an_invalid_token_is_unauthenticated(bad: str) -> None:
    with pytest.raises(UnauthenticatedError):
        verifier().verify(bad)


def test_the_unsigned_none_algorithm_is_refused() -> None:
    unsigned = jwt.encode({"sub": "alice", "exp": int(time.time()) + 60}, key="", algorithm="none")

    with pytest.raises(UnauthenticatedError):
        verifier().verify(unsigned)


def test_a_token_signed_with_an_unlisted_algorithm_is_refused() -> None:
    with pytest.raises(UnauthenticatedError):
        verifier().verify(token(secret=SECRET * 2, algorithm="HS512"))


def test_issuer_and_audience_are_enforced_when_configured() -> None:
    strict = verifier(issuer="https://idp.test", audience="sanket")

    assert strict.verify(token(iss="https://idp.test", aud="sanket")).owner_id == "alice"
    with pytest.raises(UnauthenticatedError):
        strict.verify(token(iss="https://other.test", aud="sanket"))
    with pytest.raises(UnauthenticatedError):
        strict.verify(token(iss="https://idp.test", aud="someone-else"))
    with pytest.raises(UnauthenticatedError):
        strict.verify(token(iss="https://idp.test"))


def test_a_missing_required_scope_is_forbidden_not_unauthenticated() -> None:
    needs_scope = verifier(required_scope="sanket")

    assert needs_scope.verify(token(scope="read sanket")).scopes == {"read", "sanket"}
    assert needs_scope.verify(token(scp=["sanket"])).owner_id == "alice"
    with pytest.raises(ForbiddenError):
        needs_scope.verify(token(scope="read"))


def test_a_custom_owner_claim_is_used() -> None:
    principal = verifier(owner_claim="email").verify(token(email="a@example.com"))

    assert principal.owner_id == "a@example.com"


class FixedKey:
    def __init__(self, key: Any) -> None:
        self.key = key

    def key_for(self, token: str) -> Any:
        return self.key


def test_an_rs256_token_is_verified_against_the_provider_key() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = JwtVerifier(FixedKey(private.public_key()), JWKS_ALGORITHMS, JwtSettings())
    claims = {"sub": "alice", "exp": int(time.time()) + 60}

    assert jwks.verify(jwt.encode(claims, private, "RS256")).owner_id == "alice"
    with pytest.raises(UnauthenticatedError):
        jwks.verify(jwt.encode(claims, other, "RS256"))
    # An HS256 token "signed" with the public key must not pass: no algorithm confusion.
    with pytest.raises(UnauthenticatedError):
        jwks.verify(jwt.encode(claims, SECRET, "HS256"))


# --- the authenticator --------------------------------------------------------------------


def test_the_authenticator_tries_keys_then_tokens() -> None:
    config = settings(auth_api_keys=f"svc={API_KEY}")
    auth = authenticator_from_settings(config)

    assert auth.authenticate(f"Bearer {API_KEY}").owner_id == "svc"
    assert auth.authenticate(f"bearer {token(sub='u1')}").owner_id == "u1"


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer  ", "Token abc"])
def test_a_missing_or_malformed_header_is_unauthenticated(header: str | None) -> None:
    with pytest.raises(UnauthenticatedError):
        authenticator_from_settings(settings()).authenticate(header)


def test_the_dev_bypass_admits_callers_without_credentials_as_the_default_owner() -> None:
    config = settings(auth_jwt_secret=None, auth_dev_bypass=True, default_owner_id="dev")
    auth = authenticator_from_settings(config)

    assert auth.authenticate(None).owner_id == "dev"
    # A credential that is present must still be valid.
    with pytest.raises(UnauthenticatedError):
        auth.authenticate("Bearer garbage")


def test_an_authenticator_without_any_credential_type_accepts_nobody() -> None:
    with pytest.raises(UnauthenticatedError):
        Authenticator().authenticate("Bearer something")


# --- stream tokens ------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_a_stream_token_names_its_owner_for_its_path() -> None:
    tokens = StreamTokens(STREAM_SECRET, 60, Clock())

    principal = tokens.verify(tokens.mint("alice", PATH), PATH)

    assert principal.owner_id == "alice"


def test_a_stream_token_expires() -> None:
    clock = Clock()
    tokens = StreamTokens(STREAM_SECRET, 60, clock)
    minted = tokens.mint("alice", PATH)

    clock.now += 59
    tokens.verify(minted, PATH)
    clock.now += 2
    with pytest.raises(UnauthenticatedError, match="expired"):
        tokens.verify(minted, PATH)


def test_a_stream_token_is_good_for_its_path_only() -> None:
    tokens = StreamTokens(STREAM_SECRET, 60, Clock())

    with pytest.raises(UnauthenticatedError):
        tokens.verify(tokens.mint("alice", PATH), feed_path(8))
    with pytest.raises(UnauthenticatedError):
        tokens.verify(tokens.mint("alice", PATH), "/profiles")


def test_a_tampered_or_foreign_stream_token_is_refused() -> None:
    clock = Clock()
    tokens = StreamTokens(STREAM_SECRET, 60, clock)
    other = StreamTokens("another-stream-secret-32-characters!!", 60, clock)
    version, payload, signature = tokens.mint("alice", PATH).split(".")
    forged = tokens.mint("mallory", PATH).split(".")[1]

    for bad in (
        other.mint("alice", PATH),
        f"{version}.{forged}.{signature}",
        f"{version}.{payload}",
        "garbage",
        f"{version}.é.{signature}",
        f"v2.{payload}.{signature}",
    ):
        with pytest.raises(UnauthenticatedError):
            tokens.verify(bad, PATH)


def test_a_short_stream_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="at least"):
        StreamTokens("short")


# --- startup checks -----------------------------------------------------------------------


def test_an_api_without_any_authentication_does_not_start() -> None:
    with pytest.raises(ConfigError, match="no authentication is configured"):
        check_api(settings(auth_jwt_secret=None))


def test_the_dev_bypass_is_refused_in_production() -> None:
    # The settings themselves refuse it (tests/test_dev_bypass_guard.py), so the API never
    # gets as far as its own check.
    with pytest.raises(ValidationError, match="AUTH_DEV_BYPASS"):
        settings(auth_dev_bypass=True, environment="production")


def test_weak_secrets_and_bad_keys_are_all_reported_without_values() -> None:
    config = settings(
        auth_jwt_secret="short",
        auth_stream_token_secret="short",
        auth_api_keys="alice=tiny",
        auth_jwks_url="http://idp.test/jwks",
        environment="production",
    )

    with pytest.raises(ConfigError) as caught:
        check_api(config)

    assert len(caught.value.problems) == 4
    assert "tiny" not in str(caught.value)


def test_a_valid_production_configuration_starts() -> None:
    check_api(settings(environment="production", auth_jwks_url="https://idp.test/jwks"))
    check_api(settings(auth_jwt_secret=None, auth_dev_bypass=True))
