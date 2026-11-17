"""The Redis notifier, on its own and wired into the matching service and its entry points."""

import json
import logging
from typing import Any

import fakeredis
import pytest
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine

from sanket.config import Settings
from sanket.feed.notifier import RedisMatchNotifier, notifier_from_settings
from sanket.matching import tasks
from sanket.matching.notify import NoopNotifier
from sanket.matching.service import match_job
from sanket.matching.tasks import MatchTaskDeps, registry_from_settings
from sanket.queue.base import TaskRegistry
from tests.feed_helpers import PREFIX, FakeRedisSide, record
from tests.match_helpers import add_profile, config, index_all, match_rows, seed_job

LENIENT = config(min_cosine=-1.0, min_score=0.0)
URL = "postgresql+psycopg://u:p@localhost/x"


class DownRedisClient:
    def publish(self, channel: str, message: str) -> int:
        raise RedisConnectionError("redis is down")


def subscribe(side: FakeRedisSide, profile_id: int) -> Any:
    pubsub = fakeredis.FakeRedis(server=side.server).pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(f"{PREFIX}:{profile_id}")
    return pubsub


def message_of(pubsub: Any, tries: int = 20) -> Any:
    """The next published message (the first read also consumes the subscribe confirmation)."""
    for _ in range(tries):
        message = pubsub.get_message(timeout=0.05)
        if message is not None:
            return message
    return None


def test_a_match_is_published_to_the_channel_of_its_profile() -> None:
    side = FakeRedisSide()
    listener = subscribe(side, 5)
    other = subscribe(side, 6)

    side.notifier.notify(record(11, 5, job_id=3, score=0.75, reactivated=True))

    message = message_of(listener)
    assert message is not None
    assert json.loads(message["data"]) == {
        "match_id": 11,
        "profile_id": 5,
        "job_id": 3,
        "score": 0.75,
        "reactivated": True,
    }
    assert message_of(other, tries=2) is None


def test_the_message_holds_nothing_owner_private() -> None:
    side = FakeRedisSide()
    listener = subscribe(side, 5)

    side.notifier.notify(record(1, 5, owner_id="someone", components={"secret": 1}))

    message = message_of(listener)
    assert message is not None
    text = message["data"].decode()
    assert "someone" not in text and "secret" not in text and "owner" not in text


def test_publishing_to_nobody_is_not_an_error() -> None:
    side = FakeRedisSide()

    side.notifier.notify(record(1, 5))


def test_a_redis_error_propagates_to_the_caller() -> None:
    notifier = RedisMatchNotifier(DownRedisClient(), PREFIX)  # type: ignore[arg-type]

    with pytest.raises(RedisConnectionError):
        notifier.notify(record(1, 5))


def test_the_notifier_is_the_redis_one_only_when_redis_is_configured() -> None:
    without = Settings(database_url=URL, redis_url=None)
    with_redis = Settings(database_url=URL, redis_url=SecretStr("redis://127.0.0.1:6379/0"))

    assert isinstance(notifier_from_settings(without), NoopNotifier)
    assert isinstance(notifier_from_settings(with_redis), RedisMatchNotifier)


def test_the_registry_announces_with_the_redis_notifier_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(database_url=URL, redis_url=SecretStr("redis://127.0.0.1:6379/0"))
    seen: list[object] = []

    def capture(deps: MatchTaskDeps) -> TaskRegistry:
        seen.append(deps.notifier)
        return TaskRegistry()

    monkeypatch.setattr(tasks, "build_registry", capture)

    registry_from_settings(settings, embedder=None)

    assert isinstance(seen[0], RedisMatchNotifier)


def test_a_new_match_is_published_with_its_persisted_id(clean_db: Engine) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer", work_mode="remote")
    index_all(clean_db)
    profile_id = add_profile(clean_db, summary="backend engineer python").id
    side = FakeRedisSide()
    listener = subscribe(side, profile_id)

    match_job(job_id, LENIENT, notifier=side.notifier, db_engine=clean_db)

    [row] = match_rows(clean_db)
    message = message_of(listener)
    assert message is not None
    event = json.loads(message["data"])
    assert (event["match_id"], event["job_id"], event["reactivated"]) == (row["id"], job_id, False)
    assert row["notified_at"] is not None


def test_a_dead_redis_does_not_break_matching_and_leaves_the_match_unnotified(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    job_id = seed_job(clean_db, title="Backend Engineer", work_mode="remote")
    index_all(clean_db)
    add_profile(clean_db, summary="backend engineer python")
    notifier = RedisMatchNotifier(DownRedisClient(), PREFIX)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR):
        summary = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert summary.created == 1
    [row] = match_rows(clean_db)
    assert row["status"] == "active" and row["notified_at"] is None
    assert "Notifying match" in caplog.text
