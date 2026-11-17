"""The match stream: replay, live events, dedupe, heartbeat, backpressure, cleanup, fallbacks."""

import asyncio
import json
import logging
from collections.abc import Callable
from itertools import count
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, update

import sanket.feed.stream as stream_module
from sanket.feed.limits import StreamLimiter
from sanket.matching.matches import list_matches
from sanket.models import JobMatch
from tests.feed_helpers import (
    BreaksAfterSubscribe,
    DownRedis,
    FakeRedisSide,
    drain,
    fields_of,
    frames,
    ids_of,
    make_request,
    next_frame,
    open_stream,
)
from tests.test_profile_schema import add_match, add_profile, new_job

_names = count(1)


def seed(engine: Engine, count: int, profile_id: int | None = None) -> tuple[int, list[int]]:
    """A profile with `count` active matches (each on its own job); their ids ascending."""
    profile = profile_id if profile_id is not None else add_profile(engine, name=f"p{next(_names)}")
    return profile, [add_match(engine, profile, new_job(engine)) for _ in range(count)]


def withdraw(engine: Engine, match_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(update(JobMatch).where(JobMatch.id == match_id).values(status="withdrawn"))


def run(scenario: Callable[[], Any]) -> Any:
    return asyncio.run(scenario())


# --- the first frames ---------------------------------------------------------------------


def test_the_stream_opens_with_a_retry_hint(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 0)

    async def scenario() -> str:
        stream = open_stream(make_request(clean_db, profile, retry_ms=2500))
        first = await next_frame(stream)
        await stream.aclose()
        return first

    assert run(scenario) == "retry: 2500\n\n"


def test_a_fresh_client_is_given_the_latest_id_as_its_cursor_and_no_old_matches(
    clean_db: Engine,
) -> None:
    profile, ids = seed(clean_db, 3)
    side = FakeRedisSide()

    async def scenario() -> list[str]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory))
        got = await frames(stream, 2)
        await stream.aclose()
        return got

    retry, cursor = run(scenario)
    assert retry.startswith("retry:")
    assert cursor == f"id: {ids[-1]}\n\n"


# --- replay from Last-Event-ID ------------------------------------------------------------


def test_resuming_replays_the_matches_after_the_id_in_order_then_goes_live(
    clean_db: Engine,
) -> None:
    profile, ids = seed(clean_db, 4)
    side = FakeRedisSide()

    async def scenario() -> tuple[list[str], int]:
        request = make_request(clean_db, profile, last_event_id=ids[0], redis_factory=side.factory)
        stream = open_stream(request)
        got = await frames(stream, 4)  # retry and the 3 replayed matches
        late = add_match(clean_db, profile, new_job(clean_db))
        side.publish(late, profile)
        got += await frames(stream, 1)
        await stream.aclose()
        return got, late

    got, late = run(scenario)
    assert ids_of(got) == [*ids[1:], late]
    first = fields_of(got[1])
    assert first["event"] == "match"
    assert json.loads(first["data"])["id"] == ids[1]
    assert json.loads(first["data"])["reactivated"] is False


def test_resuming_from_zero_replays_everything_and_a_current_id_replays_nothing(
    clean_db: Engine,
) -> None:
    profile, ids = seed(clean_db, 3)

    async def collect(last: int) -> list[str]:
        stream = open_stream(
            make_request(clean_db, profile, last_event_id=last, max_stream_seconds=0.1)
        )
        return await drain(stream)

    assert ids_of(run(lambda: collect(0))) == ids
    assert ids_of(run(lambda: collect(ids[-1]))) == []


def test_replay_leaves_out_withdrawn_matches_and_other_profiles(clean_db: Engine) -> None:
    profile, ids = seed(clean_db, 3)
    seed(clean_db, 2)
    withdraw(clean_db, ids[1])

    async def scenario() -> list[str]:
        request = make_request(clean_db, profile, last_event_id=0, max_stream_seconds=0.1)
        return await drain(open_stream(request))

    assert ids_of(run(scenario)) == [ids[0], ids[2]]


def test_replay_runs_in_bounded_batches_without_skipping_or_repeating(clean_db: Engine) -> None:
    profile, ids = seed(clean_db, 7)

    async def scenario() -> list[str]:
        request = make_request(
            clean_db, profile, last_event_id=0, replay_batch_size=3, max_stream_seconds=0.1
        )
        return await drain(open_stream(request))

    assert ids_of(run(scenario)) == ids


# --- live events --------------------------------------------------------------------------


def test_live_events_are_sent_in_order_as_the_stored_rows(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 1)
    side = FakeRedisSide()

    async def scenario() -> list[str]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory))
        await frames(stream, 2)
        new = [add_match(clean_db, profile, new_job(clean_db)) for _ in range(3)]
        for match_id in new:
            side.publish(match_id, profile)
        got = await frames(stream, 3)
        await stream.aclose()
        return got

    got = run(scenario)
    assert ids_of(got) == sorted(ids_of(got))
    assert len(set(ids_of(got))) == 3
    assert all(fields_of(frame)["event"] == "match" for frame in got)


def test_a_reactivated_match_is_flagged_and_sent_although_its_id_is_old(clean_db: Engine) -> None:
    profile, ids = seed(clean_db, 3)
    side = FakeRedisSide()

    async def scenario() -> dict[str, Any]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory))
        await frames(stream, 2)
        side.publish(ids[0], profile, reactivated=True)
        frame = await next_frame(stream)
        await stream.aclose()
        return fields_of(frame)

    got = run(scenario)
    assert got["id"] == str(ids[0])
    assert json.loads(got["data"])["reactivated"] is True


def test_events_for_withdrawn_foreign_and_missing_matches_and_garbage_are_dropped(
    clean_db: Engine,
) -> None:
    profile, ids = seed(clean_db, 2)
    _, foreign = seed(clean_db, 1)
    withdraw(clean_db, ids[0])
    side = FakeRedisSide()

    async def scenario() -> list[str]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory))
        await frames(stream, 2)
        side.publish(ids[0], profile)  # withdrawn since
        side.publish(foreign[0], profile)  # a row of another profile
        side.publish(9_999_999, profile)  # no such row
        side.publish(ids[1], 12345)  # claims another profile
        side.publish_raw(profile, "garbage")
        side.publish(ids[1], profile)  # the one that counts
        got = await frames(stream, 1)
        await stream.aclose()
        return got

    assert ids_of(run(scenario)) == [ids[1]]


# --- no gap and no duplicate between replay and live --------------------------------------


def test_events_published_while_replaying_are_neither_lost_nor_repeated(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, ids = seed(clean_db, 3)
    side = FakeRedisSide()
    created: list[int] = []
    real_list = list_matches

    def list_and_race(*args: Any, **kwargs: Any) -> Any:
        page = real_list(*args, **kwargs)
        if not created:
            # While the replay is reading: a match is committed and announced, and an
            # announcement arrives for a match the replay already holds.
            created.append(add_match(clean_db, profile, new_job(clean_db)))
            side.publish(created[0], profile)
            side.publish(ids[1], profile)
        return page

    async def scenario() -> list[str]:
        request = make_request(
            clean_db,
            profile,
            last_event_id=ids[0],
            redis_factory=side.factory,
            heartbeat_seconds=0.1,
        )
        stream = open_stream(request)
        got = await frames(stream, 4)  # retry, ids[1], ids[2], then the raced match
        quiet = await frames(stream, 1)  # the duplicate of ids[1] must not appear
        await stream.aclose()
        return got + quiet

    monkeypatch.setattr(stream_module, "list_matches", list_and_race)
    got = run(scenario)

    assert ids_of(got) == [ids[1], ids[2], created[0]]
    assert got[-1] == ": ping\n\n"


# --- heartbeat ----------------------------------------------------------------------------


def test_an_idle_stream_sends_heartbeat_comments(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 0)
    side = FakeRedisSide()

    async def scenario() -> list[str]:
        request = make_request(
            clean_db, profile, redis_factory=side.factory, heartbeat_seconds=0.05
        )
        stream = open_stream(request)
        got = await frames(stream, 4)
        await stream.aclose()
        return got

    got = run(scenario)
    assert got[2:] == [": ping\n\n", ": ping\n\n"]


def test_a_polling_stream_sends_heartbeats_too(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 0)

    async def scenario() -> list[str]:
        request = make_request(clean_db, profile, heartbeat_seconds=0.05, db_poll_seconds=0.01)
        stream = open_stream(request)
        got = await frames(stream, 4)
        await stream.aclose()
        return got

    assert run(scenario)[2:] == [": ping\n\n", ": ping\n\n"]


# --- disconnect and cleanup ---------------------------------------------------------------


def test_closing_the_stream_closes_the_subscription_and_frees_the_slot(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 1)
    side = FakeRedisSide()
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> tuple[int, int, bool]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory), limiter)
        await frames(stream, 2)
        during = limiter.open_streams
        await stream.aclose()
        return during, limiter.open_streams, side.closed

    during, after, closed = run(scenario)
    assert (during, after, closed) == (1, 0, True)


def test_cancelling_the_stream_task_cleans_up_like_a_client_disconnect(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 0)
    side = FakeRedisSide()
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> tuple[int, bool, int]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=side.factory), limiter)
        sent: list[str] = []

        async def consume() -> None:
            async for frame in stream:
                sent.append(frame)

        task = asyncio.create_task(consume())
        while len(sent) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return limiter.open_streams, side.closed, len(side.pubsubs)

    open_streams, closed, pubsubs = run(scenario)
    assert (open_streams, closed, pubsubs) == (0, True, 1)


def test_a_stream_that_runs_out_of_time_ends_and_cleans_up(clean_db: Engine) -> None:
    profile, _ = seed(clean_db, 0)
    side = FakeRedisSide()
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> tuple[list[str], int, bool]:
        request = make_request(
            clean_db, profile, redis_factory=side.factory, max_stream_seconds=0.15
        )
        got = await drain(open_stream(request, limiter))
        return got, limiter.open_streams, side.closed

    got, open_streams, closed = run(scenario)
    assert got[0].startswith("retry:") and open_streams == 0 and closed


# --- a slow consumer ----------------------------------------------------------------------


def test_a_consumer_that_falls_behind_the_buffer_is_dropped_and_can_resume(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    profile, [first_id] = seed(clean_db, 1)
    side = FakeRedisSide()
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> tuple[list[str], int, bool, int]:
        request = make_request(
            clean_db, profile, last_event_id=0, redis_factory=side.factory, buffer_size=3
        )
        stream = open_stream(request, limiter)
        await frames(stream, 2)  # retry and the one match; the consumer now stops reading
        new = [add_match(clean_db, profile, new_job(clean_db)) for _ in range(8)]
        for match_id in new:
            side.publish(match_id, profile)
        await asyncio.sleep(0.3)  # the subscription runs on without the consumer
        rest = await drain(stream)
        return rest, limiter.open_streams, side.closed, first_id

    with caplog.at_level(logging.INFO):
        rest, open_streams, closed, cursor = run(scenario)

    assert rest == [] and open_streams == 0 and closed
    assert "fell behind" in caplog.text

    # Resuming from the cursor the client holds gets every match it missed, in order.
    async def resume() -> list[str]:
        request = make_request(
            clean_db,
            profile,
            last_event_id=cursor,
            redis_factory=side.factory,
            max_stream_seconds=0.1,
        )
        return await drain(open_stream(request))

    assert len(ids_of(run(resume))) == 8


# --- Redis trouble ------------------------------------------------------------------------


@pytest.mark.parametrize("factory", [None, DownRedis], ids=["no-redis-configured", "redis-down"])
def test_without_redis_the_stream_replays_and_polls_the_database(
    clean_db: Engine, factory: Callable[[], Any] | None
) -> None:
    profile, ids = seed(clean_db, 2)

    async def scenario() -> list[str]:
        request = make_request(clean_db, profile, last_event_id=ids[0], redis_factory=factory)
        stream = open_stream(request)
        got = await frames(stream, 2)  # retry and the replayed match
        late = add_match(clean_db, profile, new_job(clean_db))
        got += await frames(stream, 1)  # found by the next poll
        await stream.aclose()
        return got + [f"id: {late}\n\n"]

    got = run(scenario)
    assert ids_of(got[:3]) == [ids[1], int(fields_of(got[-1])["id"])]


def test_a_fresh_client_without_redis_gets_only_matches_created_after_it_connected(
    clean_db: Engine,
) -> None:
    profile, _ = seed(clean_db, 2)

    async def scenario() -> list[str]:
        stream = open_stream(make_request(clean_db, profile, redis_factory=None))
        got = await frames(stream, 2)
        add_match(clean_db, profile, new_job(clean_db))
        got += await frames(stream, 1)
        await stream.aclose()
        return got

    got = run(scenario)
    assert len(ids_of(got)) == 1


def test_a_subscription_lost_mid_stream_ends_the_stream_so_the_client_resumes(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    profile, _ = seed(clean_db, 1)
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> list[str]:
        request = make_request(clean_db, profile, redis_factory=BreaksAfterSubscribe)
        return await asyncio.wait_for(drain(open_stream(request, limiter)), 3)

    with caplog.at_level(logging.INFO):
        got = run(scenario)

    assert got[0].startswith("retry:") and got[1].startswith("id:")
    assert limiter.open_streams == 0
    assert "subscription failed" in caplog.text


def test_a_database_error_ends_the_stream_cleanly_and_frees_the_slot(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    unreachable = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    limiter = StreamLimiter(max_streams=5, max_per_profile=5)

    async def scenario() -> list[str]:
        request = make_request(unreachable, 1, last_event_id=0)
        return await asyncio.wait_for(drain(open_stream(request, limiter)), 10)

    with caplog.at_level(logging.ERROR):
        got = run(scenario)

    assert [frame[:6] for frame in got] == ["retry:"]
    assert limiter.open_streams == 0
    assert "database error" in caplog.text
    unreachable.dispose()
