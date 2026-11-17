"""Structured logging shared by the API, the worker and every command.

`configure_logging` installs one handler on the root logger writing either JSON lines or plain
text. Both carry the request id of the request being handled (a context variable set by the API
middleware), and both pass every line through `redact`, which masks bearer tokens, passwords in
connection URLs, API keys and the like, in the message and in exception tracebacks.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

HANDLER_NAME = "sanket"
REDACTED = "***"
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
# Chatty libraries that log full URLs (the embedding key travels in a query string or header).
QUIET_LOGGERS = ("httpx", "httpcore", "google_genai", "urllib3")

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    # user:password@ in connection URLs.
    (re.compile(r"(://[^/\s:@]*:)[^@\s/]+@"), rf"\1{REDACTED}@"),
    (
        re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|stream_token|token)=)[^&\s\"']+"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(
            r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)[\"']?\s*[:=]\s*[\"']?)"
            r"(?!\*\*\*)[^\s,\"'&}]+"
        ),
        rf"\1{REDACTED}",
    ),
)
_SENSITIVE_KEY = re.compile(r"(?i)password|passwd|secret|token|api[_-]?key|authorization|cookie")
_STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _safe_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    return redact(str(value))


def _trace_id() -> str | None:
    """The active OpenTelemetry trace id, when tracing is on (the package is never imported
    here, only looked up, so it costs nothing without it)."""
    trace = sys.modules.get("opentelemetry.trace")
    if trace is None:
        return None
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: _safe_value(key, value)
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRIBUTES and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message, request id, extras, error."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            entry["request_id"] = request_id
        trace_id = _trace_id()
        if trace_id is not None:
            entry["trace_id"] = trace_id
        entry.update(_extras(record))
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """The classic one-line format, with the request id when there is one."""

    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        line = redact(super().format(record))
        request_id = request_id_var.get()
        return f"{line} request_id={request_id}" if request_id is not None else line


def configure_logging(
    level: str | None = None,
    fmt: Literal["json", "text"] | None = None,
    stream: Any = None,
) -> None:
    """Replace the root logger's handlers with one that follows the settings.

    Called by every entry point (API, worker, commands) in place of `logging.basicConfig`.
    """
    from sanket.config import settings

    handler = logging.StreamHandler(stream or sys.stderr)
    chosen = fmt or settings.effective_log_format
    handler.setFormatter(JsonFormatter() if chosen == "json" else TextFormatter())
    handler.set_name(HANDLER_NAME)
    root = logging.getLogger()
    # Keep handlers somebody else added (a test's log capture); replace only our own.
    root.handlers = [h for h in root.handlers if h.get_name() != HANDLER_NAME] + [handler]
    root.setLevel(level or settings.log_level)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
