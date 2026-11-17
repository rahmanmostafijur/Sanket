"""The match stream of one profile: replay from the database, then live events.

`match_stream` is an async generator of SSE frames. The order of things is what makes it
lossless:

1. subscribe to the profile's Redis channel (events now buffer, bounded),
2. find the starting point: the client's Last-Event-ID, or the highest match id now (a fresh
   client is sent that id so a reconnect always has a cursor),
3. replay the persisted active matches after it, in id order, in batches,
4. read the buffer: each event is a pointer, the row is loaded from the database and sent,
   unless replay already sent that id.

Without Redis (not configured, or down when the stream opens) step 1 is skipped and step 3
repeats every `db_poll_seconds`. Events are at-least-once: the same id may arrive twice (a
client must ignore an id it has seen), never zero times for a match that was committed before
the client's cursor was taken. A client that cannot keep up is closed and resumes by id.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from sanket.feed.config import FeedConfig
from sanket.feed.events import MatchEvent, channel_for
from sanket.feed.limits import StreamSlot
from sanket.feed.sse import comment_frame, event_frame, id_frame, retry_frame
from sanket.feed.subscription import RedisFactory, Subscription
from sanket.matching.matches import MatchItem, get_active_matches, latest_match_id, list_matches

logger = logging.getLogger(__name__)

EVENT_NAME = "match"
PING = "ping"
# Turns a persisted match (and whether it was just reactivated) into the JSON data of an event.
Render = Callable[[MatchItem, bool], str]


@dataclass(frozen=True)
class StreamRequest:
    profile_id: int
    # The client's resume point; None for a client that starts fresh.
    last_event_id: int | None
    cfg: FeedConfig
    db_engine: Engine
    render: Render
    # None when Redis is not configured.
    redis_factory: RedisFactory | None


class _Timer:
    """When the next heartbeat is due and when the stream has run long enough."""

    def __init__(self, heartbeat: float, lifetime: float) -> None:
        self._now = asyncio.get_running_loop().time
        self._heartbeat = heartbeat
        self._deadline = self._now() + lifetime
        self._last_write = self._now()

    def wrote(self) -> None:
        self._last_write = self._now()

    def expired(self) -> bool:
        return self._now() >= self._deadline

    def heartbeat_due(self) -> bool:
        return self._now() - self._last_write >= self._heartbeat

    def idle_budget(self) -> float:
        """Seconds until a heartbeat or the end of the stream is due, whichever is first."""
        until_heartbeat = self._last_write + self._heartbeat - self._now()
        return max(0.0, min(until_heartbeat, self._deadline - self._now()))


def _frame(item: MatchItem, reactivated: bool, render: Render) -> str:
    return event_frame(item.id, EVENT_NAME, render(item, reactivated))


async def _replay(req: StreamRequest, after_id: int) -> AsyncIterator[tuple[int, str]]:
    """The active matches after `after_id` as (id, frame), in id order, a batch at a time."""
    while True:
        page = await run_in_threadpool(
            list_matches,
            req.profile_id,
            after_id=after_id,
            limit=req.cfg.replay_batch_size,
            db_engine=req.db_engine,
        )
        for item in page.items:
            yield item.id, _frame(item, False, req.render)
        if not page.has_more or page.next_after_id is None:
            return
        after_id = page.next_after_id


async def _render_events(
    req: StreamRequest, events: Sequence[MatchEvent], skip: set[int]
) -> list[str]:
    """Frames for live events: the rows as they are now, minus ids already sent by replay."""
    reactivated: dict[int, bool] = {}
    for event in events:
        if event.profile_id == req.profile_id and event.match_id not in skip:
            reactivated[event.match_id] = (
                reactivated.get(event.match_id, False) or event.reactivated
            )
    if not reactivated:
        return []
    items = await run_in_threadpool(
        get_active_matches, req.profile_id, list(reactivated), req.db_engine
    )
    return [_frame(item, reactivated[item.id], req.render) for item in items]


def _why(sub: Subscription) -> str:
    return "the client fell behind" if sub.overflowed else "the Redis subscription failed"


async def _live(
    req: StreamRequest, sub: Subscription, cursor: int, timer: _Timer
) -> AsyncGenerator[str, None]:
    replayed: set[int] = set()
    async for item_id, frame in _replay(req, cursor):
        replayed.add(item_id)
        timer.wrote()
        yield frame
    while not timer.expired():
        if sub.overflowed or sub.failed:
            logger.info("Feed stream of profile %d closed: %s", req.profile_id, _why(sub))
            return
        events = await sub.take(req.cfg.replay_batch_size, timer.idle_budget())
        frames = await _render_events(req, events, replayed)
        for frame in frames:
            timer.wrote()
            yield frame
        if not frames and timer.heartbeat_due():
            timer.wrote()
            yield comment_frame(PING)


async def _poll(req: StreamRequest, cursor: int, timer: _Timer) -> AsyncGenerator[str, None]:
    while not timer.expired():
        async for item_id, frame in _replay(req, cursor):
            cursor = item_id
            timer.wrote()
            yield frame
        await asyncio.sleep(min(req.cfg.db_poll_seconds, timer.idle_budget()))
        if timer.heartbeat_due():
            timer.wrote()
            yield comment_frame(PING)


async def _subscribe(req: StreamRequest) -> Subscription | None:
    if req.redis_factory is None:
        return None
    channel = channel_for(req.cfg.channel_prefix, req.profile_id)
    return await Subscription.open(req.redis_factory, channel, req.cfg.buffer_size)


async def _frames(req: StreamRequest, timer: _Timer) -> AsyncGenerator[str, None]:
    sub = await _subscribe(req)
    try:
        cursor = req.last_event_id
        if cursor is None:
            # After subscribing, so a match committed from here on is also delivered live.
            cursor = await run_in_threadpool(latest_match_id, req.profile_id, req.db_engine)
            yield id_frame(cursor)
        body = _poll(req, cursor, timer) if sub is None else _live(req, sub, cursor, timer)
        async with contextlib.aclosing(body):
            async for frame in body:
                yield frame
    finally:
        if sub is not None:
            await sub.close()


async def match_stream(
    req: StreamRequest, slot: StreamSlot | None = None
) -> AsyncGenerator[str, None]:
    """The SSE frames of the stream; `slot` is released when it ends, however it ends."""
    try:
        yield retry_frame(req.cfg.retry_ms)
        timer = _Timer(req.cfg.heartbeat_seconds, req.cfg.max_stream_seconds)
        async with contextlib.aclosing(_frames(req, timer)) as frames:
            async for frame in frames:
                yield frame
    except SQLAlchemyError:
        # The status line is long sent; end cleanly and let the client reconnect and resume.
        logger.exception("Feed stream of profile %d ended: database error", req.profile_id)
    finally:
        if slot is not None:
            slot.release()
