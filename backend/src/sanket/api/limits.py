"""The rate-limit dependency: who is counted, which bucket, and the 429 answer.

Routes opt in with `Depends(RateLimit("default"))` or `RateLimit("search")`. Streaming requests
(`Accept: text/event-stream`) are never counted: a stream is one long request, and the feed is
bounded by its own connection cap instead. Callers are identified by their owner id when the
credential is valid, otherwise by client address, so unauthenticated and failing callers share
their address's budget.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status

from sanket.api.deps import ApiContext, get_context, peek_principal
from sanket.ratelimit.policy import Bucket

EVENT_STREAM = "text/event-stream"


def client_address(request: Request, trusted_hops: int) -> str:
    """The connection address, or with `trusted_hops` proxies in front, the address the
    outermost trusted proxy saw (the entry that many places from the end of X-Forwarded-For;
    entries before it can be forged by the caller)."""
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded = [part for part in forwarded if part]
    if len(forwarded) < trusted_hops:
        return peer
    return forwarded[-trusted_hops]


def is_stream_request(request: Request) -> bool:
    return EVENT_STREAM in request.headers.get("accept", "")


class RateLimit:
    def __init__(self, bucket: Bucket = "default") -> None:
        self.bucket = bucket

    def __call__(
        self,
        request: Request,
        response: Response,
        context: Annotated[ApiContext, Depends(get_context)],
    ) -> None:
        if context.limiter is None or is_stream_request(request):
            return
        principal = peek_principal(request, context)
        identity = (
            f"owner:{principal.owner_id}"
            if principal is not None
            else f"ip:{client_address(request, context.rate_limits.trusted_proxy_hops)}"
        )
        limits = context.rate_limits
        limit = limits.for_bucket(self.bucket)
        decision = context.limiter.hit(f"{self.bucket}:{identity}", limit, limits.window_seconds)
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(decision.remaining),
        }
        if not decision.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests, retry later",
                headers={**headers, "Retry-After": str(decision.retry_after)},
            )
        response.headers.update(headers)
