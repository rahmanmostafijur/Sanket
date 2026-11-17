"""Helpers for the feed tests: fake Redis on both sides, stream drivers and frame parsing."""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from typing import Any

import fakeredis
from redis.asyncio.client import PubSub
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine

from sanket.feed.config import FeedConfig
from sanket.feed.limits import StreamLimiter, StreamSlot
from sanket.feed.notifier import RedisMatchNotifier
from sanket.feed.stream import StreamRequest, match_stream
from sanket.matching.matches import MatchItem
from sanket.matching.notify import MatchRecord

PREFIX = "test:matches"
# Long enough that no heartbeat or end of stream interferes, unless a test asks for it.
QUIET = FeedConfig(
    channel_prefix=PREFIX,
    heartbeat_seconds=60,
    max_stream_seconds=60,
    db_poll_seconds=0.02,
    replay_batch_size=100,
    buffer_size=100,
)
WAIT = 3.0


def render(item: MatchItem, reactivated: bool) -> str:
    return json.dumps({"id": item.id, "job_id": item.job_id, "reactivated": reactivated})


def record(match_id: int, profile_id: int, job_id: int = 1, **fields: Any) -> MatchRecord:
    values: dict[str, Any] = {
        "match_id": match_id,
        "profile_id": profile_id,
        "owner_id": "owner-1",
        "job_id": job_id,
        "score": 0.9,
        "components": {"cosine": 0.8},
        "reactivated": False,
    }
    values.update(fields)
    return MatchRecord(**values)


class _RecordingAsyncRedis(fakeredis.FakeAsyncRedis):
    """An async client that remembers the subscriptions made through it."""

    def __init__(self, pubsubs: list[PubSub], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pubsubs = pubsubs

    def pubsub(self, **kwargs: Any) -> PubSub:
        created = super().pubsub(**kwargs)
        self._pubsubs.append(created)
        return created


class FakeRedisSide:
    """One fake Redis server, with a publishing notifier and a factory of async clients."""

    def __init__(self) -> None:
        self.server = fakeredis.FakeServer()
        self.notifier = RedisMatchNotifier(fakeredis.FakeRedis(server=self.server), PREFIX)
        self.pubsubs: list[PubSub] = []
        self.clients: list[Any] = []

    def factory(self) -> Any:
        client = _RecordingAsyncRedis(self.pubsubs, server=self.server)
        self.clients.append(client)
        return client

    def publish(self, match_id: int, profile_id: int, **fields: Any) -> None:
        self.notifier.notify(record(match_id, profile_id, **fields))

    def publish_raw(self, profile_id: int, message: str) -> None:
        fakeredis.FakeRedis(server=self.server).publish(f"{PREFIX}:{profile_id}", message)

    @property
    def closed(self) -> bool:
        """Every subscription made so far has been closed."""
        return all(pubsub.connection is None for pubsub in self.pubsubs)


class _DownPubSub:
    async def subscribe(self, *channels: str) -> None:
        raise RedisConnectionError("redis is down")

    async def aclose(self) -> None:
        return None


class DownRedis:
    """An async client of a Redis that cannot be reached."""

    def pubsub(self) -> _DownPubSub:
        return _DownPubSub()

    async def aclose(self) -> None:
        return None


class _BrokenPubSub(_DownPubSub):
    async def subscribe(self, *channels: str) -> None:
        return None

    async def get_message(self, **kwargs: Any) -> None:
        raise RedisConnectionError("connection lost")


class BreaksAfterSubscribe(DownRedis):
    """Subscribes fine, then loses the connection."""

    def pubsub(self) -> _BrokenPubSub:
        return _BrokenPubSub()


def make_request(
    engine: Engine,
    profile_id: int,
    *,
    last_event_id: int | None = None,
    redis_factory: Callable[[], Any] | None = None,
    cfg: FeedConfig = QUIET,
    **changes: Any,
) -> StreamRequest:
    return StreamRequest(
        profile_id=profile_id,
        last_event_id=last_event_id,
        cfg=replace(cfg, **changes),
        db_engine=engine,
        render=render,
        redis_factory=redis_factory,
    )


def open_stream(request: StreamRequest, limiter: StreamLimiter | None = None) -> Any:
    slot: StreamSlot | None = None if limiter is None else limiter.acquire(request.profile_id)
    return match_stream(request, slot)


async def next_frame(stream: AsyncGenerator[str, None], timeout: float = WAIT) -> str:
    return await asyncio.wait_for(stream.__anext__(), timeout)


async def frames(stream: AsyncGenerator[str, None], count: int) -> list[str]:
    return [await next_frame(stream) for _ in range(count)]


async def drain(stream: AsyncGenerator[str, None]) -> list[str]:
    """Every frame until the stream ends."""
    return [frame async for frame in stream]


def fields_of(frame: str) -> dict[str, str]:
    """The fields of one SSE frame ("id", "event", "data", and "" for a comment)."""
    result: dict[str, str] = {}
    for line in frame.strip("\n").split("\n"):
        name, _, value = line.partition(": ")
        result[name] = value
    return result


def ids_of(frame_list: list[str]) -> list[int]:
    """The ids of the match events among the frames."""
    return [int(fields_of(f)["id"]) for f in frame_list if fields_of(f).get("event") == "match"]
