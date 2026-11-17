"""The feed's small parts: events, SSE framing, stream limits, settings."""

import asyncio
import json
from typing import Any, cast

import pytest
from pydantic import SecretStr

from sanket.config import Settings
from sanket.feed.config import FeedConfig, config_from_settings
from sanket.feed.connection import redis_factory_from_settings
from sanket.feed.events import MatchEvent, channel_for, decode, encode, event_from_record
from sanket.feed.limits import StreamLimiter
from sanket.feed.sse import comment_frame, event_frame, id_frame, retry_frame
from sanket.feed.subscription import RedisFactory, Subscription
from tests.feed_helpers import DownRedis, record

# --- events ------------------------------------------------------------------------------


def test_the_channel_is_the_prefix_and_the_profile() -> None:
    assert channel_for("sanket:matches", 42) == "sanket:matches:42"


def test_an_event_survives_encoding() -> None:
    event = MatchEvent(match_id=7, profile_id=3, job_id=9, score=0.81, reactivated=True)

    assert decode(encode(event)) == event
    assert decode(encode(event).encode()) == event


def test_the_event_of_a_record_carries_no_owner_data() -> None:
    event = event_from_record(record(7, 3, job_id=9, score=0.5))

    payload = json.loads(encode(event))

    assert payload == {
        "match_id": 7,
        "profile_id": 3,
        "job_id": 9,
        "score": 0.5,
        "reactivated": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        b"\xff\xfe",
        "[]",
        "{}",
        '{"match_id": "7", "profile_id": 1, "job_id": 1, "score": 1, "reactivated": false}',
        '{"match_id": true, "profile_id": 1, "job_id": 1, "score": 1, "reactivated": false}',
        '{"match_id": 1, "profile_id": 1, "job_id": 1, "score": "x", "reactivated": false}',
    ],
)
def test_a_message_that_is_not_an_event_is_rejected(raw: str | bytes) -> None:
    with pytest.raises(ValueError, match="not a match event"):
        decode(raw)


# --- SSE framing --------------------------------------------------------------------------


def test_frames_follow_the_event_stream_format() -> None:
    assert event_frame(5, "match", '{"a":1}') == 'id: 5\nevent: match\ndata: {"a":1}\n\n'
    assert comment_frame("ping") == ": ping\n\n"
    assert retry_frame(3000) == "retry: 3000\n\n"
    assert id_frame(12) == "id: 12\n\n"


@pytest.mark.parametrize("data", ["a\nb", "a\rb"])
def test_data_with_a_line_break_is_refused(data: str) -> None:
    with pytest.raises(ValueError, match="line break"):
        event_frame(1, "match", data)


# --- the stream limiter -------------------------------------------------------------------


def test_the_limiter_caps_streams_per_profile() -> None:
    limiter = StreamLimiter(max_streams=10, max_per_profile=2)

    first, second = limiter.acquire(1), limiter.acquire(1)

    assert first is not None and second is not None
    assert limiter.acquire(1) is None
    assert limiter.acquire(2) is not None
    assert limiter.open_streams == 3


def test_the_limiter_caps_streams_in_total() -> None:
    limiter = StreamLimiter(max_streams=2, max_per_profile=5)

    assert limiter.acquire(1) is not None and limiter.acquire(2) is not None
    assert limiter.acquire(3) is None


def test_releasing_frees_the_slot_once() -> None:
    limiter = StreamLimiter(max_streams=1, max_per_profile=1)
    slot = limiter.acquire(1)
    assert slot is not None

    slot.release()
    slot.release()

    assert limiter.open_streams == 0
    assert limiter.acquire(1) is not None


# --- settings -----------------------------------------------------------------------------


def test_the_feed_config_follows_the_settings() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/x",
        feed_channel_prefix="app:m",
        feed_heartbeat_seconds=5,
        feed_retry_ms=1000,
        feed_replay_batch_size=7,
        feed_buffer_size=8,
        feed_max_streams=9,
        feed_max_streams_per_profile=2,
        feed_db_poll_seconds=1.5,
        feed_max_stream_seconds=30,
    )

    assert config_from_settings(settings) == FeedConfig(
        channel_prefix="app:m",
        heartbeat_seconds=5,
        retry_ms=1000,
        replay_batch_size=7,
        buffer_size=8,
        max_streams=9,
        max_streams_per_profile=2,
        db_poll_seconds=1.5,
        max_stream_seconds=30,
    )


URL = "postgresql+psycopg://u:p@localhost/x"


def test_the_defaults_match_the_dataclass_defaults() -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/x")

    assert config_from_settings(settings) == FeedConfig()


# --- the Redis clients of the streams -----------------------------------------------------


def test_there_is_no_client_factory_without_redis_configured() -> None:
    assert redis_factory_from_settings(Settings(database_url=URL, redis_url=None)) is None


def test_the_client_factory_applies_the_short_timeouts() -> None:
    settings = Settings(
        database_url=URL,
        redis_url=SecretStr("redis://127.0.0.1:6379/0"),
        redis_timeout_seconds=2,
    )
    factory = redis_factory_from_settings(settings)
    assert factory is not None

    client = factory()

    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 2 and kwargs["socket_connect_timeout"] == 2


# --- the subscription's edges ---------------------------------------------------------------


class ExplodingClose(DownRedis):
    async def aclose(self) -> None:
        raise OSError("already gone")


class BrokenSubscribe(DownRedis):
    def pubsub(self) -> Any:
        class Pubsub:
            async def subscribe(self, *channels: str) -> None:
                raise RuntimeError("a bug, not a Redis problem")

            async def aclose(self) -> None:
                closed.append(True)

        closed: list[bool] = []
        self.closed = closed
        return Pubsub()


def test_an_error_while_closing_a_connection_is_swallowed() -> None:
    async def scenario() -> None:
        subscription = await Subscription.open(cast(RedisFactory, ExplodingClose), "c", 5)
        assert subscription is None  # the subscribe itself failed; closing then failed too

    asyncio.run(scenario())


def test_an_unexpected_error_while_subscribing_is_raised_after_closing() -> None:
    client = BrokenSubscribe()

    async def scenario() -> None:
        await Subscription.open(cast(RedisFactory, lambda: client), "c", 5)

    with pytest.raises(RuntimeError, match="a bug"):
        asyncio.run(scenario())
    assert client.closed == [True]


def test_a_message_without_data_is_ignored() -> None:
    subscription = Subscription(DownRedis(), None, 5)  # type: ignore[arg-type]

    assert subscription._offer(None) is True
