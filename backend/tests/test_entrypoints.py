"""The API and worker commands stop at start on a configuration mistake, with a plain message."""

import pytest

from sanket.api import __main__ as api_main
from sanket.config import Settings
from sanket.worker import __main__ as worker_main

URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"


def test_the_api_refuses_to_start_without_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main, "settings", Settings.model_validate({"database_url": URL}))

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "no authentication is configured" in str(stopped.value)


def test_the_worker_refuses_to_start_in_production_without_the_embedding_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Settings.model_validate({"database_url": URL, "environment": "production"})
    monkeypatch.setattr(worker_main, "settings", config)

    with pytest.raises(SystemExit) as stopped:
        worker_main.main([])

    assert "GEMINI_API_KEY" in str(stopped.value)
