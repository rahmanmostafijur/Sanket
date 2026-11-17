"""The worker heartbeat: written with a TTL, refreshed, removed on a clean stop, expiring when
nothing refreshes it, and read back as live workers with their age. fakeredis, no network."""

import threading
import time
from collections.abc import Callable

import fakeredis
import pytest
from pydantic import SecretStr, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from rq import SimpleWorker
from sqlalchemy import Engine

from sanket.config import Settings
from sanket.worker.heartbeat import (
    HEARTBEAT_PREFIX,
    Heartbeat,
    beat_age,
    heartbeat_from_settings,
    heartbeat_key,
    read_beats,
    worker_name,
)
from sanket.worker.run import run_worker

URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"
WAIT_SECONDS = 5.0


def make_settings(**values: object) -> Settings:
    return Settings.model_validate(
        {"database_url": URL, "redis_url": SecretStr("redis://127.0.0.1:6379/0"), **values}
    )


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def stored_time(connection: fakeredis.FakeStrictRedis, name: str) -> float:
    value = connection.get(heartbeat_key(name))
    assert value is not None
    return float(value)


def wait_until(condition: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


# --- writing ------------------------------------------------------------------------------


def test_a_beat_writes_the_unix_time_with_a_ttl() -> None:
    connection = fakeredis.FakeStrictRedis()
    clock = FakeClock(1_700_000_000.5)
    heartbeat = Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45, clock=clock)

    assert heartbeat.beat() is True

    key = heartbeat_key("w1")
    assert key == f"{HEARTBEAT_PREFIX}w1" == "sanket:worker:heartbeat:w1"
    assert stored_time(connection, "w1") == pytest.approx(1_700_000_000.5)
    assert 0 < connection.ttl(key) <= 45


def test_a_later_beat_refreshes_the_time_and_the_ttl() -> None:
    connection = fakeredis.FakeStrictRedis()
    clock = FakeClock()
    heartbeat = Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45, clock=clock)
    heartbeat.beat()
    connection.expire(heartbeat_key("w1"), 5)

    clock.now += 10
    heartbeat.beat()

    assert stored_time(connection, "w1") == pytest.approx(clock.now)
    assert connection.ttl(heartbeat_key("w1")) > 5


def test_the_thread_keeps_beating_until_stopped() -> None:
    connection = fakeredis.FakeStrictRedis()
    calls: list[float] = []
    lock = threading.Lock()

    def clock() -> float:
        with lock:
            calls.append(time.time())
            return float(len(calls))

    heartbeat = Heartbeat(connection, "w1", interval_seconds=0.01, ttl_seconds=45, clock=clock)
    heartbeat.start()
    try:
        assert wait_until(lambda: len(calls) >= 4)  # the first beat plus three from the thread
    finally:
        heartbeat.stop()

    assert connection.get(heartbeat_key("w1")) is None
    settled = len(calls)
    time.sleep(0.05)
    assert len(calls) == settled  # nothing beats after stop


def test_a_clean_stop_removes_the_key() -> None:
    connection = fakeredis.FakeStrictRedis()
    with Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45):
        assert connection.exists(heartbeat_key("w1")) == 1

    assert connection.exists(heartbeat_key("w1")) == 0


def test_a_killed_worker_leaves_a_key_that_expires() -> None:
    connection = fakeredis.FakeStrictRedis()
    heartbeat = Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45)
    heartbeat.beat()  # the process then dies: nobody refreshes or deletes the key

    connection.pexpire(heartbeat_key("w1"), 1)
    time.sleep(0.01)

    assert connection.exists(heartbeat_key("w1")) == 0
    assert read_beats(connection, max_age_seconds=45) == []


def test_a_second_start_is_refused() -> None:
    heartbeat = Heartbeat(fakeredis.FakeStrictRedis(), "w1", interval_seconds=10, ttl_seconds=45)
    heartbeat.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            heartbeat.start()
    finally:
        heartbeat.stop()


class DownRedis:
    def set(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("down")

    def delete(self, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("down")


def test_a_redis_failure_is_reported_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    heartbeat = Heartbeat(
        DownRedis(),  # type: ignore[arg-type]
        "w1",
        interval_seconds=10,
        ttl_seconds=45,
    )

    assert heartbeat.beat() is False
    heartbeat.stop()  # must not raise either

    assert "worker heartbeat not written: ConnectionError" in caplog.text
    assert "worker heartbeat not removed: ConnectionError" in caplog.text


# --- reading ------------------------------------------------------------------------------


def test_the_reader_counts_live_workers_and_computes_their_age() -> None:
    connection = fakeredis.FakeStrictRedis()
    clock = FakeClock(1000.0)
    Heartbeat(connection, "b", interval_seconds=10, ttl_seconds=45, clock=clock).beat()
    clock.now = 1007.5
    Heartbeat(connection, "a", interval_seconds=10, ttl_seconds=45, clock=clock).beat()
    clock.now = 1010.0

    beats = read_beats(connection, max_age_seconds=45, clock=clock)

    assert [(beat.name, beat.age_seconds) for beat in beats] == [("a", 2.5), ("b", 10.0)]


def test_a_beat_older_than_the_limit_is_not_alive_even_if_the_key_is_still_there() -> None:
    connection = fakeredis.FakeStrictRedis()
    clock = FakeClock(1000.0)
    Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45, clock=clock).beat()

    clock.now = 1046.0

    assert read_beats(connection, max_age_seconds=45, clock=clock) == []
    assert beat_age(connection, "w1", max_age_seconds=45, clock=clock) is None
    clock.now = 1044.0
    assert beat_age(connection, "w1", max_age_seconds=45, clock=clock) == pytest.approx(44.0)


def test_other_keys_and_unreadable_values_are_ignored() -> None:
    connection = fakeredis.FakeStrictRedis()
    connection.set("sanket:other", "1")
    connection.set(heartbeat_key("garbled"), "not-a-number")

    assert read_beats(connection, max_age_seconds=45) == []
    assert beat_age(connection, "garbled", max_age_seconds=45) is None
    assert beat_age(connection, "missing", max_age_seconds=45) is None


def test_a_clock_behind_the_writer_never_gives_a_negative_age() -> None:
    connection = fakeredis.FakeStrictRedis()
    Heartbeat(connection, "w1", interval_seconds=10, ttl_seconds=45, clock=FakeClock(2000.0)).beat()

    (beat,) = read_beats(connection, max_age_seconds=45, clock=FakeClock(1990.0))

    assert beat.age_seconds == 0.0


def test_the_reader_raises_when_redis_is_down() -> None:
    class Broken:
        def scan_iter(self, *args: object, **kwargs: object) -> None:
            raise RedisConnectionError("down")

    with pytest.raises(RedisConnectionError):
        read_beats(Broken(), max_age_seconds=45)  # type: ignore[arg-type]


# --- settings -----------------------------------------------------------------------------


def test_the_worker_is_named_by_the_setting_or_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sanket.worker.heartbeat.socket.gethostname", lambda: "container-7f3a")

    assert worker_name(make_settings(worker_name="worker-1")) == "worker-1"
    assert worker_name(make_settings(worker_name=None)) == "container-7f3a"
    assert worker_name(make_settings(worker_name="  ")) == "container-7f3a"


def test_the_heartbeat_takes_its_timing_from_the_settings() -> None:
    connection = fakeredis.FakeStrictRedis()
    config = make_settings(
        worker_name="w9", worker_heartbeat_interval_seconds=2, worker_heartbeat_ttl_seconds=20
    )

    heartbeat_from_settings(config, connection).beat()

    assert 0 < connection.ttl(heartbeat_key("w9")) <= 20


def test_the_defaults_are_valid_and_leave_room_for_missed_beats() -> None:
    config = make_settings()

    assert config.worker_heartbeat_interval_seconds == 10
    assert config.worker_heartbeat_ttl_seconds == 45
    assert config.worker_heartbeat_ttl_seconds >= 3 * config.worker_heartbeat_interval_seconds


@pytest.mark.parametrize(
    "values",
    [
        {"worker_heartbeat_interval_seconds": 0},
        {"worker_heartbeat_interval_seconds": -1},
        {"worker_heartbeat_interval_seconds": 301},
        {"worker_heartbeat_ttl_seconds": 2},
        {"worker_heartbeat_ttl_seconds": 3601},
        {"worker_name": "has space"},
        {"worker_name": "x" * 101},
    ],
)
def test_out_of_range_worker_settings_are_refused(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**values)


def test_a_ttl_shorter_than_three_beats_is_refused_and_named() -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(worker_heartbeat_interval_seconds=20, worker_heartbeat_ttl_seconds=59)

    assert "WORKER_HEARTBEAT_TTL_SECONDS must be at least 3 times" in str(caught.value)
    make_settings(worker_heartbeat_interval_seconds=20, worker_heartbeat_ttl_seconds=60)


# --- the worker process -----------------------------------------------------------------------


def test_the_worker_beats_while_it_works_and_removes_the_key_when_it_stops(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = fakeredis.FakeStrictRedis()
    seen: list[bool] = []

    def fake_work(self: SimpleWorker, **kwargs: object) -> bool:
        seen.append(connection.exists(heartbeat_key("w-run")) == 1)
        return False

    monkeypatch.setattr(SimpleWorker, "work", fake_work)

    run_worker(
        make_settings(worker_name="w-run"),
        burst=True,
        simple=True,
        connection=connection,
        db_engine=clean_db,
    )

    assert seen == [True]
    assert connection.exists(heartbeat_key("w-run")) == 0


def test_the_key_is_removed_when_the_worker_stops_on_an_error(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = fakeredis.FakeStrictRedis()

    def failing_work(self: SimpleWorker, **kwargs: object) -> bool:
        raise KeyboardInterrupt

    monkeypatch.setattr(SimpleWorker, "work", failing_work)

    with pytest.raises(KeyboardInterrupt):
        run_worker(
            make_settings(worker_name="w-err"),
            burst=False,
            simple=True,
            connection=connection,
            db_engine=clean_db,
        )

    assert connection.exists(heartbeat_key("w-err")) == 0


def test_the_heartbeat_keeps_going_while_the_worker_thread_is_blocked_in_a_task(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = fakeredis.FakeStrictRedis()
    stamps: list[float] = []

    def long_work(self: SimpleWorker, **kwargs: object) -> bool:
        # The worker thread waits here for a while, like a long task, and the key moves on.
        first = connection.get(heartbeat_key("w-long"))
        assert first is not None
        assert wait_until(lambda: connection.get(heartbeat_key("w-long")) != first)
        stamps.append(stored_time(connection, "w-long"))
        return True

    monkeypatch.setattr(SimpleWorker, "work", long_work)

    run_worker(
        make_settings(worker_name="w-long", worker_heartbeat_interval_seconds=0.01),
        burst=True,
        simple=True,
        connection=connection,
        db_engine=clean_db,
    )

    assert len(stamps) == 1
