"""Structured logging: JSON lines, request id, redaction, and the shared configuration."""

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from sanket.observability.logs import (
    HANDLER_NAME,
    JsonFormatter,
    TextFormatter,
    configure_logging,
    redact,
    request_id_var,
)


def record(message: str = "hello", *args: Any, **extra: Any) -> logging.LogRecord:
    made = logging.LogRecord("sanket.test", logging.INFO, __file__, 1, message, args, None)
    made.__dict__.update(extra)
    return made


@pytest.fixture
def restore_root() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers, root.level = handlers, level


def test_a_json_line_has_time_level_logger_and_message() -> None:
    line = json.loads(JsonFormatter().format(record("loaded %d rows", 3)))

    assert (line["level"], line["logger"], line["message"]) == (
        "INFO",
        "sanket.test",
        "loaded 3 rows",
    )
    assert line["time"].endswith("+00:00") and "request_id" not in line


def test_the_request_id_is_in_every_line_while_it_is_set() -> None:
    token = request_id_var.set("req-123")
    try:
        data = json.loads(JsonFormatter().format(record()))
        text = TextFormatter().format(record())
    finally:
        request_id_var.reset(token)

    assert data["request_id"] == "req-123"
    assert text.endswith("request_id=req-123")


def test_extra_fields_become_keys_and_sensitive_names_are_masked() -> None:
    line = json.loads(JsonFormatter().format(record(duration_ms=1.5, api_key="abc", note="ok")))

    assert (line["duration_ms"], line["note"], line["api_key"]) == (1.5, "ok", "***")


def test_an_exception_is_included_as_text_and_redacted() -> None:
    try:
        raise RuntimeError("connect failed postgresql://user:hunter2@db:5432/x")
    except RuntimeError:
        import sys

        made = record()
        made.exc_info = sys.exc_info()

    line = json.loads(JsonFormatter().format(made))

    assert "RuntimeError" in line["exception"]
    assert "hunter2" not in line["exception"] and "user:***@db" in line["exception"]


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("sent header bearer eyJhbGciOi.payload.sig", "eyJhbGciOi"),
        ("db postgresql+psycopg://sanket:p%40ss@127.0.0.1:5433/x", "p%40ss"),
        ("redis://:pw0rd@cache:6379/0", "pw0rd"),
        ("GET https://api.example/v1?key=AIzaSyABC&page=2", "AIzaSyABC"),
        ("GET /profiles/1/matches/stream?stream_token=v1.aaa.bbb", "v1.aaa.bbb"),
        ("settings password=hunter2 user=x", "hunter2"),
        ('{"api_key": "sekret-value"}', "sekret-value"),
    ],
)
def test_credentials_are_masked_in_messages(raw: str, secret: str) -> None:
    assert secret not in redact(raw)
    assert secret not in JsonFormatter().format(record(raw))
    assert secret not in TextFormatter().format(record(raw))


def test_text_without_credentials_is_left_alone() -> None:
    message = "indexed 12 jobs in 3.2s (host=db key count=4)"

    assert redact(message) == message


def test_configure_logging_installs_one_handler_of_the_chosen_format(restore_root: None) -> None:
    stream = io.StringIO()

    configure_logging(level="INFO", fmt="json", stream=stream)
    configure_logging(level="INFO", fmt="json", stream=stream)
    logging.getLogger("sanket.x").info("hi %s", "there")

    ours = [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]
    assert len(ours) == 1
    assert json.loads(stream.getvalue())["message"] == "hi there"


def test_configure_logging_keeps_foreign_handlers_and_quiets_http_clients(
    restore_root: None,
) -> None:
    foreign = logging.NullHandler()
    logging.getLogger().addHandler(foreign)

    configure_logging(level="WARNING", fmt="text", stream=io.StringIO())

    assert foreign in logging.getLogger().handlers
    assert logging.getLogger().level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
