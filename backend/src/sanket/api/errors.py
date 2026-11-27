"""One JSON error envelope for every failure the API can answer with.

```json
{"error": {"code": "not_found", "message": "profile not found", "request_id": "...",
           "details": [...]}}
```

`code` is a stable machine-readable word, `message` is for people, `request_id` matches the
`X-Request-ID` response header and the log lines of the request, and `details` appears for
validation errors only (location, message and type of each problem, never the submitted values).
Unhandled exceptions are logged with their traceback and answered with a generic 500, so no
internals leak. Successful responses are untouched.
"""

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from sanket.observability.logs import request_id_var

logger = logging.getLogger(__name__)

GENERIC_500 = "internal server error"
VALIDATION_MESSAGE = "the request is invalid"
ACCOUNT_GONE = "the account for this token no longer exists, sign in again"
# The foreign keys from owned tables to `users` (named by the naming convention in models.py).
_ACCOUNT_FOREIGN_KEY = re.compile(r"^fk_\w+_user_id_users$")

_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def error_code(status_code: int) -> str:
    return _CODES.get(status_code, f"http_{status_code}")


def error_body(
    status_code: int, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": error_code(status_code),
        "message": message,
        "request_id": request_id_var.get(),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(
    status_code: int,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(status_code, message, details), status_code, headers)


def internal_error_response() -> JSONResponse:
    return error_response(500, GENERIC_500)


def _validation_details(errors: list[Any]) -> list[dict[str, Any]]:
    """Location, message and type only: `input` would echo what the caller sent."""
    return [
        {
            "loc": [part if isinstance(part, int) else str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in errors
    ]


def _json_safe_details(detail: Any) -> list[dict[str, Any]] | None:
    """A list detail (a service's validation errors) becomes `details`; others are dropped."""
    if not isinstance(detail, list):
        return None
    return _validation_details(
        [item if isinstance(item, dict) else {"msg": item} for item in detail]
    )


async def _http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    details = _json_safe_details(exc.detail)
    if isinstance(exc.detail, str):
        message = exc.detail
    elif details is not None:
        message = VALIDATION_MESSAGE
    else:
        message = error_code(exc.status_code).replace("_", " ")
    return error_response(exc.status_code, message, details, dict(exc.headers or {}))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, VALIDATION_MESSAGE, _validation_details(list(exc.errors())))


async def _integrity_error(request: Request, exc: Exception) -> JSONResponse:
    """A valid token can outlive its account (the token is not checked against the database), so
    a write that points at the missing account is a 401, not a crash. Any other integrity error
    is a bug and is raised on to the request middleware, which answers the generic 500."""
    assert isinstance(exc, IntegrityError)
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if isinstance(constraint, str) and _ACCOUNT_FOREIGN_KEY.match(constraint):
        return error_response(401, ACCOUNT_GONE, headers={"WWW-Authenticate": "Bearer"})
    raise exc


def install_error_handlers(app: FastAPI) -> None:
    """Answer HTTP errors and validation errors with the envelope. Unhandled exceptions are
    handled by the request middleware, which sits outside every handler."""
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(IntegrityError, _integrity_error)
