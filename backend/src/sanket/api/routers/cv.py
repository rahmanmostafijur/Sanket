"""`POST /cv/import`: read a CV and propose a profile. Nothing is saved.

The request body is the file itself (not a multipart form), read straight into memory with a
hard size cap: multipart parsers spool large uploads to a temporary file, and a CV must never
touch the disk. The file is judged by its content, not its name or declared type. Neither the
file nor its text is stored or logged. Each owner may import a few times per window, because
every call is a request to the language model provider.

Statuses: 401 no credential, 413 over 5 MB, 422 not a PDF or DOCX or nothing readable in it
(a scanned file), 429 too many imports, 503 the provider's quota is used up (with
`Retry-After`) or CV import is not configured, 502 any other provider failure or an answer
that never fit the fields.
"""

import logging
import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from sanket.api.deps import ApiContext, get_context, get_owner_id
from sanket.cv.reader import (
    MAX_CV_BYTES,
    CvError,
    CvTooLargeError,
    detect_format,
    read_cv,
)
from sanket.cv.schema import CvProposal
from sanket.cv.service import CvProposalError, propose_profile
from sanket.extraction.llm import LlmError, LlmRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cv", tags=["cv"])

Context = Annotated[ApiContext, Depends(get_context)]
Owner = Annotated[str, Depends(get_owner_id)]

DEFAULT_RETRY_SECONDS = 60
DAILY_QUOTA_RETRY_SECONDS = 3600
MAX_RETRY_SECONDS = 86_400
TOO_LARGE = "the file is larger than 5 MB"
EMPTY_FILE = "the request has no file"
NOT_CONFIGURED = "CV import is not available: no language model is configured"
PROVIDER_FAILED = "the language model could not read the CV, try again"


def _limit_by_owner(context: ApiContext, owner: str) -> None:
    limiter = context.auth_limiter
    if limiter is None:
        return
    limits = context.rate_limits
    decision = limiter.hit(f"cv:owner:{owner}", limits.cv_requests, limits.window_seconds)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many CV imports, retry later",
            headers={"Retry-After": str(decision.retry_after)},
        )


async def _read_body(request: Request) -> bytes:
    """The whole body, refusing at once when it is, or grows, past the limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_CV_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_CV_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _quota_response(error: LlmRateLimitError) -> HTTPException:
    if error.retry_after is not None:
        wait = math.ceil(error.retry_after)
    else:
        wait = DAILY_QUOTA_RETRY_SECONDS if error.daily else DEFAULT_RETRY_SECONDS
    wait = max(1, min(wait, MAX_RETRY_SECONDS))
    if error.daily:
        message = "the language model's daily quota is used up, try again later"
    else:
        message = f"the language model is at its limit, try again in about {wait} seconds"
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, message, headers={"Retry-After": str(wait)}
    )


@router.post(
    "/import",
    response_model=CvProposal,
    summary="Read a CV into a proposed profile",
    description=(
        "Send the PDF or DOCX file as the request body (at most 5 MB). Returns the career profile "
        "the CV states (personal details, education, experience, skills, languages, certifications, projects); what it does not state is empty. Nothing is "
        "stored: save the profile yourself after reviewing it."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def import_cv(
    request: Request, response: Response, context: Context, owner: Owner
) -> CvProposal:
    _limit_by_owner(context, owner)
    data = await _read_body(request)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, EMPTY_FILE)
    try:
        text = await run_in_threadpool(read_cv, data)
    except CvTooLargeError:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE) from None
    except CvError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    client = context.llm_client
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    logger.info("CV import: %s, %d bytes", detect_format(data), len(data))
    try:
        proposal = await run_in_threadpool(propose_profile, client, text)
    except LlmRateLimitError as error:
        raise _quota_response(error) from None
    except (LlmError, CvProposalError) as error:
        # The type only: a provider's message is not worth risking next to a person's CV.
        logger.warning("CV import failed: %s", type(error).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, PROVIDER_FAILED) from None
    response.headers["Cache-Control"] = "no-store"
    return proposal
