"""Request context for every HTTP request: id, access log, timing and unhandled errors.

Pure ASGI (not `BaseHTTPMiddleware`) so streaming responses are never buffered and the context
variable reaches the handler. The middleware

- accepts an `X-Request-ID` of a safe shape or makes one, returns it in the response and puts
  it in every log line of the request;
- writes one access log line per request: method, path, status and duration. The query string
  is never logged (stream tokens travel in it);
- reports each finished request to an optional observer (the metrics), labelled with the route
  template, never the raw path;
- turns an exception that escaped the app into the generic 500 envelope after logging it with
  its traceback, so the response still carries the request id.
"""

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sanket.api.errors import internal_error_response
from sanket.observability.logs import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
UNMATCHED_ROUTE = "unmatched"
# Probes and scrapes are logged at DEBUG: they would drown the real traffic.
QUIET_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})

access_logger = logging.getLogger("sanket.access")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestRecord:
    method: str
    route: str
    path: str
    status: int
    duration_seconds: float


Observer = Callable[[RequestRecord], None]


def new_request_id() -> str:
    return uuid.uuid4().hex


def route_template(scope: Scope) -> str:
    """The matched route's path template (`/profiles/{profile_id}`), else `unmatched`."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, observer: Observer | None = None) -> None:
        self.app = app
        self.observer = observer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        try:
            await self._handle(scope, receive, send, request_id)
        finally:
            request_id_var.reset(token)

    async def _handle(self, scope: Scope, receive: Receive, send: Send, request_id: str) -> None:
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("unhandled error: %s %s", scope["method"], scope["path"])
            if response_started:
                raise
            status = 500
            await internal_error_response()(scope, receive, send_with_id)
        self._finish(scope, status, time.perf_counter() - started)

    def _finish(self, scope: Scope, status: int, duration: float) -> None:
        record = RequestRecord(
            method=scope["method"],
            route=route_template(scope),
            path=scope["path"],
            status=status,
            duration_seconds=duration,
        )
        level = logging.DEBUG if record.path in QUIET_PATHS else logging.INFO
        access_logger.log(
            level,
            "%s %s %d %.1fms",
            record.method,
            record.path,
            record.status,
            duration * 1000,
            extra={
                "request_id": request_id_var.get(),
                "http_method": record.method,
                "http_path": record.path,
                "http_status": record.status,
                "duration_ms": round(duration * 1000, 1),
            },
        )
        if self.observer is not None:
            self.observer(record)
