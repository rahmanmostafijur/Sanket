"""The live feed stage of the end-to-end test.

Matches produced by the pipeline are published by the real `RedisMatchNotifier` (on a fake
Redis) and read from `GET /profiles/{id}/matches/stream` with a streaming ASGI client. The
pipeline steps are blocking calls made inside the same event loop as the open streams: the
events they publish wait in each stream's subscription until the loop runs again.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.feed.events import MatchEvent, decode
from tests.e2e import data, sse
from tests.e2e import pipeline as p
from tests.feed_helpers import PREFIX

OTHER_OWNER = "e2e-other-owner"
# How long the publish log waits for a message that is not there yet (they are already queued).
POLL_SECONDS = 0.02
T = TypeVar("T")


class PublishLog:
    """Listens on every profile channel of the fake Redis, next to the streams, so the tests can
    see what the notifier published and to which channel, whatever the streams do with it."""

    def __init__(self, stack: p.Stack) -> None:
        assert stack.redis is not None
        self._pubsub = fakeredis.FakeRedis(server=stack.redis.server).pubsub()
        self._pubsub.psubscribe(f"{PREFIX}:*")
        assert self._pubsub.get_message(timeout=1.0)["type"] == "psubscribe"
        self.published: list[tuple[int, MatchEvent]] = []

    def collect(self) -> list[tuple[int, MatchEvent]]:
        """Everything published so far as (profile id from the channel, message), in order."""
        while (message := self._pubsub.get_message(timeout=POLL_SECONDS)) is not None:
            channel = message["channel"].decode()
            self.published.append((int(channel.rsplit(":", 1)[1]), decode(message["data"])))
        return list(self.published)

    def match_ids(self, profile_id: int) -> list[int]:
        return [event.match_id for channel, event in self.collect() if channel == profile_id]


class Feed:
    """Two owners with one profile each, the same criteria, both ready to be matched."""

    def __init__(self, stack: p.Stack) -> None:
        self.stack = stack
        self.app_a: FastAPI = p.api_app(stack)
        self.app_b: FastAPI = p.api_app(stack, default_owner_id=OTHER_OWNER)
        self.log = PublishLog(stack)
        self.client_a = TestClient(self.app_a)
        self.client_b = TestClient(self.app_b)
        self.profile_a: int = p.create_profile(self.client_a, data.PROFILE_BODY)["id"]
        self.profile_b: int = p.create_profile(self.client_b, data.PROFILE_BODY)["id"]
        assert p.drain_queue(stack) == 4  # embed and match each profile; no jobs exist yet

    def stream_path(self, profile_id: int) -> str:
        return f"/profiles/{profile_id}/matches/stream"

    def matches(self, client: TestClient, profile_id: int) -> list[dict[str, Any]]:
        return p.matches_of(client, profile_id)

    def match_ids(self, client: TestClient, profile_id: int) -> list[int]:
        return [m["id"] for m in self.matches(client, profile_id)]


@pytest.fixture
def feed(clean_db: Engine) -> Feed:
    return Feed(p.build_feed_stack(clean_db))


def run(scenario: Callable[[], Awaitable[T]]) -> T:
    async def wrapper() -> T:
        return await scenario()

    return asyncio.run(wrapper())


def titles(events: list[sse.MatchEvent]) -> list[str]:
    return sorted(event.data["job"]["title"] for event in events)


# -- live delivery -------------------------------------------------------------------------------


def test_matches_made_by_the_pipeline_arrive_on_the_stream_of_their_own_profile(
    feed: Feed,
) -> None:
    stack = feed.stack
    assert stack.redis is not None

    async def scenario() -> tuple[list[sse.MatchEvent], list[sse.MatchEvent], p.PipelineRun]:
        conn_a = await sse.open_live(feed.app_a, feed.profile_a)
        conn_b = await sse.open_live(feed.app_b, feed.profile_b)
        pipeline_run = p.run_pipeline(stack, data.first_run_feeds())
        events_a = await conn_a.events(len(data.EXPECTED_FIRST_MATCHES))
        events_b = await conn_b.events(len(data.EXPECTED_FIRST_MATCHES))
        quiet = await conn_a.quiet() and await conn_b.quiet()
        assert quiet, "a stream received more than its own profile's matches"
        await conn_a.close()
        await conn_b.close()
        return events_a, events_b, pipeline_run

    events_a, events_b, pipeline_run = run(scenario)

    assert pipeline_run.tasks_run == data.FIRST_RUN_JOBS
    ids_a = feed.match_ids(feed.client_a, feed.profile_a)
    ids_b = feed.match_ids(feed.client_b, feed.profile_b)
    assert len(ids_a) == len(ids_b) == len(data.EXPECTED_FIRST_MATCHES)
    assert not set(ids_a) & set(ids_b)
    # The event id is the persisted match id, and the right profile's stream got it.
    assert sorted(e.id for e in events_a) == ids_a
    assert sorted(e.id for e in events_b) == ids_b
    # What the notifier published: one message per match, on the channel of its own profile.
    assert sorted(feed.log.match_ids(feed.profile_a)) == ids_a
    assert sorted(feed.log.match_ids(feed.profile_b)) == ids_b
    assert len(feed.log.collect()) == len(ids_a) + len(ids_b)
    assert titles(events_a) == titles(events_b) == data.EXPECTED_FIRST_MATCHES
    for event in events_a:
        assert event.data["id"] == event.id
        assert (event.data["status"], event.data["reactivated"]) == ("active", False)
        assert event.data["job"]["url"] and event.data["job"]["attribution"]
    # Delivered means the PUBLISH was accepted; every match was marked, and none was missed.
    snapshot = p.match_snapshot(stack.engine)
    assert len(snapshot) == len(ids_a) + len(ids_b)
    assert all(row[6] is not None for row in snapshot)
    assert stack.redis.closed, "a subscription was left open after the clients left"


def test_the_event_shows_the_match_as_it_is_stored(feed: Feed) -> None:
    async def scenario() -> list[sse.MatchEvent]:
        conn = await sse.open_live(feed.app_a, feed.profile_a)
        p.run_pipeline(feed.stack, data.first_run_feeds())
        events = await conn.events(len(data.EXPECTED_FIRST_MATCHES))
        await conn.close()
        return events

    events = run(scenario)

    stored = {m["id"]: m for m in feed.matches(feed.client_a, feed.profile_a)}
    for event in events:
        row = stored[event.id]
        assert event.data["job_id"] == row["job_id"]
        assert event.data["score"] == row["score"]
        assert event.data["job"]["title"] == row["job"]["title"]
        assert event.data["components"] == row["components"]


def test_a_profile_saved_after_the_jobs_is_matched_and_streamed_the_same_way(
    clean_db: Engine,
) -> None:
    stack = p.build_feed_stack(clean_db)
    log = PublishLog(stack)
    p.run_pipeline(stack, data.first_run_feeds())
    assert log.collect() == []  # no profile yet, so nothing to announce
    app = p.api_app(stack)
    client = TestClient(app)

    async def scenario() -> tuple[int, list[sse.MatchEvent]]:
        # The stream opens on a profile that does not exist yet: create it first, then listen,
        # then let the profile-side matching run (embed, then match against the indexed jobs).
        profile_id = p.create_profile(client, data.PROFILE_BODY)["id"]
        conn = await sse.open_live(app, profile_id)
        p.drain_queue(stack)
        events = await conn.events(len(data.EXPECTED_FIRST_MATCHES))
        await conn.close()
        return profile_id, events

    profile_id, events = run(scenario)

    stored = sorted(m["id"] for m in p.matches_of(client, profile_id))
    assert sorted(e.id for e in events) == stored
    assert sorted(log.match_ids(profile_id)) == stored


# -- resuming ------------------------------------------------------------------------------------


def three_matches(feed: Feed) -> list[int]:
    """Run both feeds so profile A holds three matches; returns their ids, ascending."""
    p.run_pipeline(feed.stack, data.first_run_feeds())
    p.run_pipeline(feed.stack, data.second_run_feeds())
    ids = feed.match_ids(feed.client_a, feed.profile_a)
    assert len(ids) == 3
    return ids


def test_last_event_id_replays_exactly_the_matches_after_it(feed: Feed) -> None:
    ids = three_matches(feed)

    async def scenario() -> dict[str, list[int]]:
        seen: dict[str, list[int]] = {}
        for label, headers, query in [
            ("after first", {"Last-Event-ID": str(ids[0])}, ""),
            ("after last", {"Last-Event-ID": str(ids[2])}, ""),
            ("from zero", {"Last-Event-ID": "0"}, ""),
            ("query", {}, f"last_event_id={ids[1]}"),
        ]:
            conn = await sse.open_sse(
                feed.app_a, feed.stream_path(feed.profile_a), headers=headers, query=query
            )
            assert conn.status == 200
            replayed: list[int] = []
            while True:
                try:
                    replayed.append((await conn.next_event(0.3)).id)
                except (TimeoutError, EOFError):
                    break
            await conn.close()
            seen[label] = replayed
        return seen

    seen = run(scenario)

    assert seen == {
        "after first": ids[1:],
        "after last": [],
        "from zero": ids,
        "query": ids[2:],
    }


def test_a_fresh_stream_sends_nothing_that_already_exists_and_gets_later_matches(
    feed: Feed,
) -> None:
    ids = three_matches(feed)

    async def scenario() -> tuple[str, bool]:
        conn = await sse.open_sse(feed.app_a, feed.stream_path(feed.profile_a))
        await conn.next_frame()  # the retry hint
        cursor = sse.fields_of(await conn.next_frame())
        quiet = await conn.quiet()
        await conn.close()
        return cursor["id"], quiet

    cursor, quiet = run(scenario)

    assert cursor == str(ids[-1])  # the resume point is the newest match
    assert quiet


def test_a_client_that_reconnects_with_its_last_id_misses_nothing_and_repeats_nothing(
    feed: Feed,
) -> None:
    async def scenario() -> tuple[list[int], list[int]]:
        conn = await sse.open_live(feed.app_a, feed.profile_a)
        p.run_pipeline(feed.stack, data.first_run_feeds())
        first = await conn.events(len(data.EXPECTED_FIRST_MATCHES))
        await conn.close()  # the client drops away; a new listing is matched meanwhile
        p.run_pipeline(feed.stack, data.second_run_feeds())
        again = await sse.open_sse(
            feed.app_a,
            feed.stream_path(feed.profile_a),
            headers={"Last-Event-ID": str(first[-1].id)},
        )
        missed = await again.events(1)
        quiet = await again.quiet()
        await again.close()
        assert quiet
        return [e.id for e in first], [e.id for e in missed]

    first, missed = run(scenario)

    everything = feed.match_ids(feed.client_a, feed.profile_a)
    assert first + missed == everything
    assert len(set(first + missed)) == len(everything)


# -- owners --------------------------------------------------------------------------------------


def test_a_profile_of_another_owner_is_a_404_and_reveals_nothing(feed: Feed) -> None:
    async def scenario() -> list[int]:
        statuses = []
        for app, profile_id in [
            (feed.app_a, feed.profile_b),  # exists, but belongs to the other owner
            (feed.app_b, feed.profile_a),
            (feed.app_a, feed.profile_b + 1000),  # does not exist
        ]:
            conn = await sse.open_sse(app, feed.stream_path(profile_id))
            statuses.append(conn.status)
            await conn.close()
        return statuses

    assert run(scenario) == [404, 404, 404]


def test_a_profile_that_matches_nothing_gets_no_events_while_the_other_owner_does(
    feed: Feed,
) -> None:
    unmatched = p.create_profile(
        feed.client_b, {**data.PROFILE_BODY, "name": "No match", "required_skills": ["COBOL"]}
    )["id"]
    p.drain_queue(feed.stack)

    async def scenario() -> tuple[list[sse.MatchEvent], bool]:
        quiet_conn = await sse.open_live(feed.app_b, unmatched)
        busy_conn = await sse.open_live(feed.app_a, feed.profile_a)
        p.run_pipeline(feed.stack, data.first_run_feeds())
        events = await busy_conn.events(len(data.EXPECTED_FIRST_MATCHES))
        quiet = await quiet_conn.quiet()
        await busy_conn.close()
        await quiet_conn.close()
        return events, quiet

    events, quiet = run(scenario)

    assert quiet
    assert titles(events) == data.EXPECTED_FIRST_MATCHES
    assert feed.matches(feed.client_b, unmatched) == []
    assert feed.log.match_ids(unmatched) == []


# -- reruns --------------------------------------------------------------------------------------


def test_a_rerun_publishes_nothing_and_a_new_listing_exactly_one_event(feed: Feed) -> None:
    assert feed.stack.redis is not None

    async def scenario() -> tuple[list[int], list[sse.MatchEvent], bool, bool]:
        conn = await sse.open_live(feed.app_a, feed.profile_a)
        p.run_pipeline(feed.stack, data.first_run_feeds())
        first = await conn.events(len(data.EXPECTED_FIRST_MATCHES))
        before = p.match_snapshot(feed.stack.engine)
        published = len(feed.log.collect())
        rerun = p.run_pipeline(feed.stack, data.first_run_feeds())
        rerun_quiet = await conn.quiet()
        unchanged = (
            p.match_snapshot(feed.stack.engine) == before
            and rerun.tasks_run == 0
            and len(feed.log.collect()) == published
        )
        p.run_pipeline(feed.stack, data.second_run_feeds())
        new = await conn.events(1)
        new_quiet = await conn.quiet()
        await conn.close()
        return [e.id for e in first], new, rerun_quiet and unchanged, new_quiet

    first, new, rerun_clean, new_quiet = run(scenario)

    assert rerun_clean, "a rerun changed matches or published events"
    assert new_quiet
    assert new[0].data["job"]["title"] == data.STAFF
    assert new[0].id > max(first)
    assert feed.match_ids(feed.client_a, feed.profile_a) == [*first, new[0].id]
    assert feed.log.match_ids(feed.profile_a) == [*first, new[0].id]  # each published once
    assert feed.stack.redis.closed


def test_a_withdrawal_is_not_an_event_and_is_not_replayed(
    feed: Feed,
) -> None:
    ids = three_matches(feed)

    async def scenario() -> tuple[bool, list[int]]:
        conn = await sse.open_live(feed.app_a, feed.profile_a)
        p.remove_posting(feed.stack.engine, "remotive", "8002")
        run_after = p.run_pipeline(feed.stack, [])
        quiet = await conn.quiet()  # a withdrawal is not an event
        await conn.close()
        assert run_after.indexing.removed == 1
        replay = await sse.open_sse(
            feed.app_a, feed.stream_path(feed.profile_a), headers={"Last-Event-ID": "0"}
        )
        replayed = [e.id for e in await replay.events(2)]
        gone = await replay.quiet()
        await replay.close()
        assert gone
        return quiet, replayed

    quiet, replayed = run(scenario)

    assert quiet
    active = feed.match_ids(feed.client_a, feed.profile_a)
    assert len(active) == 2 and replayed == active
    assert set(active) < set(ids)
