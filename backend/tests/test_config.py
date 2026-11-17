"""Settings: secrets stay secret, the environment is validated, role checks list every problem."""

import pytest
from pydantic import ValidationError

from sanket.config import Settings
from sanket.runtime_checks import ConfigError, check_worker, ensure_valid

PASSWORD = "s3cret-pw"
URL = f"postgresql+psycopg://user:{PASSWORD}@127.0.0.1:5433/x_test"


def make(**values: object) -> Settings:
    return Settings.model_validate({"database_url": URL, **values})


def test_the_database_url_is_a_secret_in_repr_and_dumps() -> None:
    config = make(test_database_url=URL)

    assert PASSWORD not in repr(config)
    assert PASSWORD not in config.model_dump_json()
    assert config.database_dsn == URL


def test_the_environment_defaults_to_development_and_is_validated() -> None:
    assert make().environment == "development"
    assert make(environment="production").is_production
    with pytest.raises(ValidationError):
        make(environment="staging")


def test_a_worker_in_production_needs_the_embedding_key() -> None:
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        check_worker(make(environment="production"))

    check_worker(make(environment="production", gemini_api_key="k"))
    check_worker(make())


def test_every_problem_is_reported_together() -> None:
    with pytest.raises(ConfigError) as caught:
        ensure_valid(["first", "second"])

    assert caught.value.problems == ["first", "second"]
    assert "first; second" in str(caught.value)
