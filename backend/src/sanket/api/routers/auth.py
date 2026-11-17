"""`POST /auth/stream-token`: a short-lived token for opening the match stream from a browser."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from sanket.api.deps import ApiContext, get_context, get_header_owner_id
from sanket.auth.stream_token import QUERY_PARAMETER, feed_path
from sanket.profiles import service

router = APIRouter(prefix="/auth", tags=["auth"])


class StreamTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: int = Field(gt=0, description="The profile whose match stream will be opened.")


class StreamTokenOut(BaseModel):
    token: str
    expires_in: int = Field(description="Seconds the token stays valid.")
    path: str = Field(description="The only path the token opens.")
    query_parameter: str = Field(description="Send the token as this query parameter.")


@router.post(
    "/stream-token",
    response_model=StreamTokenOut,
    summary="Mint a stream token",
    description=(
        "For clients that cannot send an Authorization header (a browser EventSource). The "
        "token is bound to your owner id and to the match stream of one of your profiles, and "
        "expires in about a minute. A profile that is not yours is a 404."
    ),
)
def mint_stream_token(
    body: StreamTokenRequest,
    context: Annotated[ApiContext, Depends(get_context)],
    owner: Annotated[str, Depends(get_header_owner_id)],
) -> StreamTokenOut:
    if context.stream_tokens is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream tokens are not enabled")
    try:
        service.get(owner, body.profile_id, context.db_engine)
    except service.ProfileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found") from None
    path = feed_path(body.profile_id)
    return StreamTokenOut(
        token=context.stream_tokens.mint(owner, path),
        expires_in=context.stream_tokens.ttl_seconds,
        path=path,
        query_parameter=QUERY_PARAMETER,
    )
