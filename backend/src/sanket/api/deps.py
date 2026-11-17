"""What request handlers share: the application context, read from `app.state`."""

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine

from sanket.auth.authenticator import Authenticator
from sanket.auth.errors import AuthError
from sanket.auth.principal import Principal
from sanket.auth.stream_token import QUERY_PARAMETER, StreamTokens
from sanket.embeddings.client import EmbeddingClient
from sanket.queue.base import TaskQueue
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
    # Who a request is (see `get_principal`). The default accepts nobody.
    authenticator: Authenticator = field(default_factory=Authenticator)
    # None when stream tokens are not configured (see sanket.auth.stream_token).
    stream_tokens: StreamTokens | None = None
    # Whether GET /search may be called without credentials.
    search_public: bool = False


def get_context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


def _http_error(error: AuthError) -> HTTPException:
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if error.status_code == status.HTTP_401_UNAUTHORIZED
        else None
    )
    return HTTPException(error.status_code, error.message, headers=headers)


def get_header_principal(
    request: Request, context: Annotated[ApiContext, Depends(get_context)]
) -> Principal:
    """The caller, from the `Authorization` header only (401 or 403 otherwise)."""
    try:
        return context.authenticator.authenticate(request.headers.get("authorization"))
    except AuthError as error:
        raise _http_error(error) from None


def get_principal(
    request: Request, context: Annotated[ApiContext, Depends(get_context)]
) -> Principal:
    """The caller: the `Authorization` header, or a stream token in the query string.

    A stream token is accepted only without an Authorization header and only for the exact path
    it was minted for, so it opens that one stream and nothing else.
    """
    token = request.query_params.get(QUERY_PARAMETER)
    if token is not None and "authorization" not in request.headers and context.stream_tokens:
        try:
            return context.stream_tokens.verify(token, request.url.path)
        except AuthError as error:
            raise _http_error(error) from None
    return get_header_principal(request, context)


def get_owner_id(principal: Annotated[Principal, Depends(get_principal)]) -> str:
    """The opaque id of the owner a request acts for: the authenticated caller.

    Every owner-scoped route depends on this, and every profile query is scoped by what it
    returns. A route that must not accept stream tokens uses `get_header_owner_id`.
    """
    return principal.owner_id


def get_header_owner_id(principal: Annotated[Principal, Depends(get_header_principal)]) -> str:
    return principal.owner_id


def require_search_access(
    request: Request, context: Annotated[ApiContext, Depends(get_context)]
) -> None:
    """Search is open only when SEARCH_PUBLIC is set; otherwise it needs a credential."""
    if not context.search_public:
        get_header_principal(request, context)
