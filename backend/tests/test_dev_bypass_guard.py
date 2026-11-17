"""The development bypass is refused in production, by the settings themselves.

`Settings` raises when ENVIRONMENT=production and AUTH_DEV_BYPASS is on, so every process that
imports `sanket.config` (api, worker, ingest, alembic, the CLIs) stops at start. Development and
test allow the bypass; the one rule is "never in production".
"""

import os
import subprocess
import sys
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sanket.auth.authenticator import authenticator_from_settings, dev_bypass_allowed
from sanket.auth.errors import UnauthenticatedError
from sanket.config import DEV_BYPASS_IN_PRODUCTION, Settings, describe_settings_error
from sanket.runtime_checks import ConfigError, check_api
from tests.auth_helpers import settings as api_settings

PASSWORD = "s3cret-pw-9f3a"
URL = f"postgresql+psycopg://user:{PASSWORD}@127.0.0.1:5433/x_test"
SUBPROCESS_TIMEOUT_SECONDS = 60


def build(**values: Any) -> Settings:
    return Settings.model_validate({"database_url": URL, **values})


# --- the settings ------------------------------------------------------------------------


def test_production_with_the_bypass_fails_at_construction() -> None:
    with pytest.raises(ValidationError, match="AUTH_DEV_BYPASS must not be enabled"):
        build(environment="production", auth_dev_bypass=True)


def test_the_environment_variable_path_fails_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "true")

    with pytest.raises(ValidationError, match="ENVIRONMENT=production"):
        Settings(_env_file=None, database_url=URL)  # type: ignore[call-arg]


def test_the_environment_can_come_from_a_variable_and_the_bypass_from_an_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="AUTH_DEV_BYPASS"):
        Settings(_env_file=None, database_url=URL, auth_dev_bypass=True)  # type: ignore[call-arg]


@pytest.mark.parametrize("environment", ["development", "test"])
def test_the_bypass_is_allowed_in_development_and_test(environment: str) -> None:
    config = build(environment=environment, auth_dev_bypass=True)

    assert config.auth_dev_bypass is True
    assert dev_bypass_allowed(config)


def test_production_without_the_bypass_is_fine() -> None:
    config = build(environment="production", auth_dev_bypass=False)

    assert config.is_production
    assert not dev_bypass_allowed(config)
    assert build(environment="production").auth_dev_bypass is False


def test_the_error_names_the_settings_and_carries_no_secret_value() -> None:
    with pytest.raises(ValidationError) as caught:
        build(
            environment="production",
            auth_dev_bypass=True,
            gemini_api_key="gemini-key-value-123",
            auth_jwt_secret="jwt-secret-value-that-is-long-enough-1",
            redis_url="redis://:redis-pw-value@127.0.0.1:6379/0",
        )

    text = str(caught.value) + repr(caught.value)
    assert DEV_BYPASS_IN_PRODUCTION in text
    for secret in (PASSWORD, "gemini-key-value-123", "jwt-secret-value", "redis-pw-value"):
        assert secret not in text


# --- the rest of the code follows the same rule ---------------------------------------------


def test_the_authenticator_lets_the_bypass_in_during_test_too() -> None:
    config = api_settings(auth_jwt_secret=None, auth_dev_bypass=True, environment="test")

    assert authenticator_from_settings(config).authenticate(None).method == "dev"


def test_the_api_check_accepts_the_bypass_in_test_as_the_only_authentication() -> None:
    check_api(api_settings(auth_jwt_secret=None, auth_dev_bypass=True, environment="test"))


def test_a_settings_object_that_skipped_validation_is_still_refused_at_the_api_check() -> None:
    config = api_settings(environment="production", auth_jwks_url="https://idp.test/jwks")
    forced = config.model_copy(update={"auth_dev_bypass": True})

    assert not dev_bypass_allowed(forced)
    with pytest.raises(ConfigError, match="AUTH_DEV_BYPASS must not be enabled"):
        check_api(forced)
    with pytest.raises(UnauthenticatedError):
        authenticator_from_settings(forced).authenticate(None)


def test_the_no_authentication_message_names_the_one_rule() -> None:
    with pytest.raises(ConfigError) as caught:
        check_api(api_settings(auth_jwt_secret=None))

    assert "outside ENVIRONMENT=production" in str(caught.value)
    assert "only works with ENVIRONMENT=development" not in str(caught.value)


# --- the processes ----------------------------------------------------------------------------


def run_module(*args: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "DATABASE_URL": URL,
        "ENVIRONMENT": "production",
        "AUTH_DEV_BYPASS": "true",
        "GEMINI_API_KEY": "gemini-key-value-123",
        "AUTH_JWT_SECRET": "jwt-secret-value-that-is-long-enough-1",
    }
    return subprocess.run(
        [sys.executable, "-m", *args],
        env=environment,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )


@pytest.mark.parametrize(
    "module",
    [["sanket.api"], ["sanket.worker", "--burst"], ["sanket.ingest"]],
    ids=["api", "worker", "ingest"],
)
def test_a_process_refuses_to_start_in_production_with_the_bypass(module: list[str]) -> None:
    result = run_module(*module)

    assert result.returncode != 0
    assert "invalid configuration" in result.stderr
    assert DEV_BYPASS_IN_PRODUCTION in result.stderr
    assert "Traceback" not in result.stderr
    for secret in (PASSWORD, "gemini-key-value-123", "jwt-secret-value"):
        assert secret not in result.stderr + result.stdout


def test_a_missing_required_setting_is_described_by_name_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, gemini_api_key=SecretStr("gemini-key-value-123"))  # type: ignore[call-arg]

    message = describe_settings_error(caught.value)

    assert message.startswith("invalid configuration: ")
    assert "DATABASE_URL" in message
    assert "gemini-key-value-123" not in message
    assert len(message.splitlines()) == 1


def test_a_value_error_is_described_without_its_prefix() -> None:
    with pytest.raises(ValidationError) as caught:
        build(environment="production", auth_dev_bypass=True)

    assert describe_settings_error(caught.value) == (
        f"invalid configuration: {DEV_BYPASS_IN_PRODUCTION}"
    )
