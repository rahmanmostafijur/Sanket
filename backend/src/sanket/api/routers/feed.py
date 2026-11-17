"""The live match feed of a profile, as Server-Sent Events.

Owner scoping is the same as the other profile routes: a profile that is not yours is a 404, so
ids reveal nothing. How the stream works is in `sanket.feed.stream` and docs/feed.md.
"""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from sanket.api.deps import ApiContext, get_context, get_owner_id
from sanket.api.profile_schemas import MatchEventOut
from sanket.feed.sse import MEDIA_TYPE
from sanket.feed.stream import StreamRequest, match_stream
from sanket.matching.matches import MatchItem
from sanket.profiles import service

router = APIRouter(prefix="/profiles", tags=["feed"])

Context = Annotated[ApiContext, Depends(get_context)]
Owner = Annotated[str, Depends(get_owner_id)]

# Match ids are 64-bit integers.
MAX_EVENT_ID = 2**63 - 1
STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Tell nginx not to buffer the stream.
    "X-Accel-Buffering": "no",
}


def parse_last_event_id(header: str | None, query: str | None) -> int | None:
    """The client's resume point, or None for a fresh client.

    The header (which a browser sends when it reconnects, and is then newer than the URL it
    was opened with) wins over `last_event_id` in the query string. Blank means none; anything
    that is not a match id is a 400.
    """
    raw = next((value.strip() for value in (header, query) if value and value.strip()), None)
    if raw is None:
        return None
    if not (raw.isascii() and raw.isdecimal()) or int(raw) > MAX_EVENT_ID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid Last-Event-ID")
    return int(raw)


def _render(item: MatchItem, reactivated: bool) -> str:
    return MatchEventOut.from_match(item, reactivated=reactivated).model_dump_json()


@router.get(
    "/{profile_id}/matches/stream",
    summary="Stream the matches of a profile as they happen",
    description=(
        "Server-Sent Events: one `match` event per new (or reactivated) match, whose `id` is "
        "the match id and whose data is the match as in the match list plus `reactivated`. "
        "Resume with the `Last-Event-ID` header (a browser sends it by itself when it "
        "reconnects) or `last_event_id` in the query: the active matches after it are sent "
        "first, then live ones. A fresh client gets live matches only. Events can repeat; "
        "ignore an id you have seen. Withdrawals are not streamed. Lines starting with `:` "
        "are heartbeats. 429 when too many streams are open."
    ),
    response_class=StreamingResponse,
    responses={
        200: {"content": {MEDIA_TYPE: {}}, "description": "The event stream."},
        400: {"description": "Last-Event-ID is not a match id."},
        404: {"description": "No such profile."},
        429: {"description": "Too many open streams."},
    },
)
async def stream_matches(
    profile_id: int,
    context: Context,
    owner: Owner,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    last_event_id: Annotated[
        str | None, Query(description="Resume point for clients that cannot send the header.")
    ] = None,
) -> StreamingResponse:
    try:
        await run_in_threadpool(service.get, owner, profile_id, context.db_engine)
    except service.ProfileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "profile not found") from None
    cursor = parse_last_event_id(last_event_id_header, last_event_id)
    cfg = context.feed_config
    slot = context.feed_limiter.acquire(profile_id)
    if slot is None:
        retry_after = str(max(1, math.ceil(cfg.retry_ms / 1000)))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many open streams",
            headers={"Retry-After": retry_after},
        )
    stream = match_stream(
        StreamRequest(
            profile_id=profile_id,
            last_event_id=cursor,
            cfg=cfg,
            db_engine=context.db_engine,
            render=_render,
            redis_factory=context.feed_redis,
        ),
        slot,
    )
    # The generator releases the slot itself; the background task covers a response that is
    # abandoned before the first chunk is pulled. Releasing twice is harmless.
    return StreamingResponse(
        stream,
        media_type=MEDIA_TYPE,
        headers=STREAM_HEADERS,
        background=BackgroundTask(slot.release),
    )
