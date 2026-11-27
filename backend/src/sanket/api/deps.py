"""What request handlers share: the application context, read from `app.state`."""

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine

from sanket.accounts.identity import user_id_of
from sanket.accounts.tokens import AccessTokens
from sanket.api.health import ReadinessProbe
from sanket.auth.authenticator import Authenticator
from sanket.auth.errors import AuthError
from sanket.auth.principal import Principal
from sanket.auth.stream_token import QUERY_PARAMETER, StreamTokens
from sanket.embeddings.client import EmbeddingClient
from sanket.extraction.llm import LlmClient
from sanket.feed.config import FeedConfig
from sanket.feed.limits import StreamLimiter
from sanket.feed.subscription import RedisFactory
from sanket.observability.metrics import ApiMetrics
from sanket.queue.base import TaskQueue
from sanket.ratelimit.limiter import RateLimiter
from sanket.ratelimit.policy import RateLimits
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.retrieval import SearchConfig


@dataclass(frozen=True)
class ApiContext:
    db_engine: Engine
    search_config: SearchConfig
    # None when no embedding provider is configured: search then answers from full text only.
    embedding_client: EmbeddingClient | None
    query_cache: QueryEmbeddingCache
    # None when Redis is not configured: profiles are saved and wait to be embedded.
    task_queue: TaskQueue | None
    default_owner_id: str
    max_profiles_per_owner: int
    feed_config: FeedConfig
    feed_limiter: StreamLimiter
    # Opens a Redis client for one stream; None when Redis is not configured (streams then
    # poll the database).
    feed_redis: RedisFactory | None
    # Who a request is (see `get_principal`). The default accepts nobody.
    authenticator: Authenticator = field(default_factory=Authenticator)
    # None when stream tokens are not configured (see sanket.auth.stream_token).
    stream_tokens: StreamTokens | None = None
    # Signs the access tokens of email and password accounts; None without AUTH_JWT_SECRET.
    access_tokens: AccessTokens | None = None
    # None when rate limiting is off (see sanket.api.limits).
    limiter: RateLimiter | None = None
    # Sign-up, log-in and CV imports are always limited: this is `limiter`, or a per-process
    # one when rate limiting is off.
    auth_limiter: RateLimiter | None = None
    # Reads CVs; None without an API key (CV import then answers 503).
    llm_client: LlmClient | None = None
    rate_limits: RateLimits = field(default_factory=RateLimits)
    # None disables /readyz checks (always ready) and /metrics (404) respectively.
    readiness: ReadinessProbe | None = None
    metrics: ApiMetrics | None = None
    # The bearer token /metrics requires, when one is configured.
    metrics_token: str | None = None


def get_context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


def _http_error(error: AuthError) -> HTTPException:
    unauthenticated = error.status_code == status.HTTP_401_UNAUTHORIZED
    headers = {"WWW-Authenticate": "Bearer"} if unauthenticated else None
    return HTTPException(error.status_code, error.message, headers=headers)


def _lookup(
    request: Request, context: ApiContext, allow_stream_token: bool
) -> Principal | AuthError:
    """Who is calling, or why not. Worked out once per request and kept on `request.state`,
    so the rate limiter and the route's own dependency do not verify the token twice."""
    attribute = "auth_with_stream_token" if allow_stream_token else "auth_header_only"
    cached: Principal | AuthError | None = getattr(request.state, attribute, None)
    if cached is not None:
        return cached
    token = request.query_params.get(QUERY_PARAMETER) if allow_stream_token else None
    try:
        if token is not None and "authorization" not in request.headers and context.stream_tokens:
            result: Principal | AuthError = context.stream_tokens.verify(token, request.url.path)
        else:
            result = context.authenticator.authenticate(request.headers.get("authorization"))
    except AuthError as error:
        result = error
    setattr(request.state, attribute, result)
    return result


def _require(result: Principal | AuthError) -> Principal:
    if isinstance(result, AuthError):
        raise _http_error(result)
    return result


def get_header_principal(
    request: Request, context: Annotated[ApiContext, Depends(get_context)]
) -> Principal:
    """The caller, from the `Authorization` header only (401 or 403 otherwise)."""
    return _require(_lookup(request, context, allow_stream_token=False))


def get_principal(
    request: Request, context: Annotated[ApiContext, Depends(get_context)]
) -> Principal:
    """The caller: the `Authorization` header, or a stream token in the query string.

    A stream token is accepted only without an Authorization header and only for the exact path
    it was minted for, so it opens that one stream and nothing else.
    """
    return _require(_lookup(request, context, allow_stream_token=True))


def peek_principal(request: Request, context: ApiContext) -> Principal | None:
    """The caller if the credential is valid, else None; never raises."""
    result = _lookup(request, context, allow_stream_token=False)
    return None if isinstance(result, AuthError) else result


def get_owner_id(principal: Annotated[Principal, Depends(get_principal)]) -> str:
    """The opaque id of the owner a request acts for: the authenticated caller.

    Every owner-scoped route depends on this, and every profile query is scoped by what it
    returns. A route that must not accept stream tokens uses `get_header_owner_id`.
    """
    return principal.owner_id


def get_header_owner_id(principal: Annotated[Principal, Depends(get_header_principal)]) -> str:
    return principal.owner_id


NO_ACCOUNT = "this credential has no account"


def get_account_id(owner: Annotated[str, Depends(get_owner_id)]) -> uuid.UUID:
    """The account a request acts for. Only email and password accounts have a career profile:
    an API key or the development owner is answered 404, so a client can tell there is none."""
    user_id = user_id_of(owner)
    if user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ACCOUNT)
    return user_id
