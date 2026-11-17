"""When `python -m sanket.extraction.runner` exits non-zero.

No database and no network: `run_batch` and the Gemini client are replaced, and every Settings
a test uses is built with `_env_file=None` and explicit values, so a local `.env` cannot change
the outcome.
"""

import logging
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sanket.config import Settings
from sanket.extraction import runner
from sanket.extraction.runner import (
    MAX_CONSECUTIVE_PROVIDER_ERRORS,
    BatchResult,
    Outcome,
    batch_failure,
)

URL = "postgresql+psycopg://user:pw@127.0.0.1:5433/x_test"
DEFAULT_RATIO = 0.2


def make_settings(**values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=URL, gemini_api_key=SecretStr("not-a-real-key"), **values
    )


def result(*, ok: int = 0, failed: int = 0, errors: int = 0, skipped: int = 0, early: bool = False):
    counts = {
        Outcome.OK: ok,
        Outcome.FAILED: failed,
        Outcome.PROVIDER_ERROR: errors,
        Outcome.SKIPPED: skipped,
    }
    return BatchResult({outcome: n for outcome, n in counts.items() if n}, stopped_early=early)


def run_main(monkeypatch: pytest.MonkeyPatch, batch: BatchResult, config: Settings) -> None:
    monkeypatch.setattr(runner, "settings", config)
    monkeypatch.setattr(runner, "configure_logging", lambda: None)
    monkeypatch.setattr(runner, "GeminiClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner, "run_batch", lambda *args, **kwargs: batch)
    runner.main()


# --- the rule -----------------------------------------------------------------------------


def test_one_provider_error_in_fifty_postings_passes() -> None:
    assert batch_failure(result(ok=49, errors=1), DEFAULT_RATIO) is None


def test_fifteen_provider_errors_in_fifty_postings_fails() -> None:
    message = batch_failure(result(ok=35, errors=15), DEFAULT_RATIO)

    assert message is not None
    assert "15 of 50" in message


def test_a_ratio_equal_to_the_limit_passes() -> None:
    assert batch_failure(result(ok=40, errors=10), DEFAULT_RATIO) is None


def test_a_batch_with_nothing_attempted_passes() -> None:
    assert batch_failure(result(), DEFAULT_RATIO) is None
    assert batch_failure(result(skipped=3), DEFAULT_RATIO) is None


def test_skipped_postings_are_not_counted_as_attempts() -> None:
    # 1 error in 4 attempts is 0.25; counting the 46 skipped postings would make it 0.02.
    assert batch_failure(result(ok=3, errors=1, skipped=46), DEFAULT_RATIO) is not None


def test_validation_failures_count_as_attempts_but_not_as_provider_errors() -> None:
    assert batch_failure(result(ok=39, failed=10, errors=1), DEFAULT_RATIO) is None


def test_the_early_stop_fails_even_when_the_ratio_is_low() -> None:
    stopped = result(ok=40, errors=MAX_CONSECUTIVE_PROVIDER_ERRORS, early=True)

    message = batch_failure(stopped, DEFAULT_RATIO)

    assert message is not None
    assert "in a row" in message


def test_a_limit_of_zero_fails_on_any_provider_error() -> None:
    assert batch_failure(result(ok=49, errors=1), 0.0) is not None
    assert batch_failure(result(ok=50), 0.0) is None


def test_a_limit_of_one_fails_only_on_the_early_stop() -> None:
    assert batch_failure(result(errors=2), 1.0) is None
    assert batch_failure(result(errors=3, early=True), 1.0) is not None


# --- the setting --------------------------------------------------------------------------


def test_the_limit_defaults_to_a_fifth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTRACTION_MAX_PROVIDER_ERROR_RATIO", raising=False)

    assert make_settings().extraction_max_provider_error_ratio == DEFAULT_RATIO


def test_the_limit_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACTION_MAX_PROVIDER_ERROR_RATIO", "0.5")

    assert make_settings().extraction_max_provider_error_ratio == 0.5


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_a_limit_outside_zero_to_one_is_refused(value: float) -> None:
    with pytest.raises(ValidationError, match="extraction_max_provider_error_ratio"):
        make_settings(extraction_max_provider_error_ratio=value)


@pytest.mark.parametrize("value", [0, 1])
def test_the_bounds_are_allowed(value: float) -> None:
    assert make_settings(extraction_max_provider_error_ratio=value)


# --- main ---------------------------------------------------------------------------------


def test_main_exits_zero_and_warns_for_a_provider_error_under_the_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="sanket.extraction.runner")

    run_main(monkeypatch, result(ok=49, errors=1), make_settings())

    summary = next(r for r in caplog.records if "extraction summary" in r.getMessage())
    assert "ok=49" in summary.getMessage() and "provider_error=1" in summary.getMessage()
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "1 of 50" in warning.getMessage() and "pending" in warning.getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_main_does_not_warn_when_there_were_no_provider_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="sanket.extraction.runner")

    run_main(monkeypatch, result(ok=50), make_settings())

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_main_exits_non_zero_above_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="15 of 50"):
        run_main(monkeypatch, result(ok=35, errors=15), make_settings())


def test_main_exits_non_zero_after_the_early_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = result(ok=40, errors=MAX_CONSECUTIVE_PROVIDER_ERRORS, early=True)

    with pytest.raises(SystemExit, match="in a row"):
        run_main(monkeypatch, stopped, make_settings())


def test_main_takes_the_limit_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = result(ok=35, errors=15)

    with pytest.raises(SystemExit):
        run_main(monkeypatch, batch, make_settings())
    run_main(monkeypatch, batch, make_settings(extraction_max_provider_error_ratio=0.5))
    with pytest.raises(SystemExit):
        run_main(monkeypatch, batch, make_settings(extraction_max_provider_error_ratio=0.1))


def test_main_exits_zero_for_an_empty_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    run_main(monkeypatch, result(), make_settings())
