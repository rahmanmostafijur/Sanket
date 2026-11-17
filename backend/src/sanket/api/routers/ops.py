"""Operational endpoints: `/healthz` (liveness), `/readyz` (readiness) and `/metrics`.

They are public and not rate limited, and answer outside the error envelope's usual flow:
orchestrators and Prometheus read the status code. `/metrics` is guarded by its own token (see
`Settings.metrics_token`) instead of a user credential.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sanket.api.deps import ApiContext, get_context

router = APIRouter(tags=["ops"])

Context = Annotated[ApiContext, Depends(get_context)]
BEARER_PREFIX = "bearer "


@router.get("/healthz", summary="Liveness: the process is serving requests")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/readyz",
    summary="Readiness: the database (and Redis, when configured) answer",
    responses={503: {"description": "A dependency is not ready."}},
)
def readyz(context: Context) -> JSONResponse:
    if context.readiness is None:
        return JSONResponse({"status": "ready", "checks": {}})
    result = context.readiness.run()
    code = status.HTTP_200_OK if result.ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(result.body(), status_code=code)


def _token_matches(request: Request, expected: str) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        return False
    return hmac.compare_digest(header[len(BEARER_PREFIX) :].strip().encode(), expected.encode())


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
def metrics(request: Request, context: Context) -> Response:
    if context.metrics is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if context.metrics_token is not None and not _token_matches(request, context.metrics_token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "metrics token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Response(generate_latest(context.metrics.registry), media_type=CONTENT_TYPE_LATEST)
