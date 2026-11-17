"""`python -m sanket.worker --check`: exit 0 only while this worker's heartbeat is fresh."""

import os
import subprocess
import sys

import fakeredis
import pytest
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from sanket.config import Settings
from sanket.worker import __main__ as cli
from sanket.worker import check as check_module
from sanket.worker.check import HEALTHY, UNHEALTHY, check_worker_alive
from sanket.worker.heartbeat import Heartbeat

URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"
REDIS_PASSWORD = "redis-pw-1234"
REDIS_URL = f"redis://:{REDIS_PASSWORD}@127.0.0.1:1/0"


def make_settings(**values: object) -> Settings:
    return Settings.model_validate(
        {
            "database_url": URL,
            "redis_url": SecretStr(REDIS_URL),
            "worker_name": "w-check",
            "worker_heartbeat_ttl_seconds": 45,
            "redis_timeout_seconds": 0.2,
            **values,
        }
    )


def beat_at(connection: fakeredis.FakeStrictRedis, name: str, moment: float) -> None:
    Heartbeat(connection, name, interval_seconds=10, ttl_seconds=45, clock=lambda: moment).beat()


def test_a_fresh_heartbeat_is_healthy() -> None:
    connection = fakeredis.FakeStrictRedis()
    beat_at(connection, "w-check", 1000.0)

    status, reason = check_worker_alive(make_settings(), connection, clock=lambda: 1003.0)

    assert status == HEALTHY == 0
    assert "w-check is alive" in reason and "3.0s" in reason


def test_a_missing_heartbeat_is_unhealthy() -> None:
    status, reason = check_worker_alive(make_settings(), fakeredis.FakeStrictRedis())

    assert status == UNHEALTHY == 1
    assert "no fresh heartbeat" in reason


def test_a_stale_heartbeat_is_unhealthy_even_before_redis_expires_the_key() -> None:
    connection = fakeredis.FakeStrictRedis()
    beat_at(connection, "w-check", 1000.0)

    status, _ = check_worker_alive(make_settings(), connection, clock=lambda: 1046.0)

    assert status == UNHEALTHY


def test_only_this_workers_own_heartbeat_counts() -> None:
    connection = fakeredis.FakeStrictRedis()
    beat_at(connection, "some-other-worker", 1000.0)

    status, _ = check_worker_alive(make_settings(), connection, clock=lambda: 1001.0)

    assert status == UNHEALTHY


def test_an_unreachable_redis_is_unhealthy_and_the_url_is_not_echoed() -> None:
    status, reason = check_worker_alive(make_settings())

    assert status == UNHEALTHY
    assert "cannot read the heartbeat" in reason
    assert REDIS_PASSWORD not in reason and "127.0.0.1" not in reason


def test_a_redis_that_fails_on_read_is_unhealthy() -> None:
    class Broken:
        def get(self, *args: object) -> None:
            raise RedisConnectionError("down")

    status, reason = check_worker_alive(make_settings(), Broken())  # type: ignore[arg-type]

    assert status == UNHEALTHY
    assert "ConnectionError" in reason


def test_without_redis_there_is_nothing_to_read() -> None:
    status, reason = check_worker_alive(make_settings(redis_url=None))

    assert status == UNHEALTHY
    assert "REDIS_URL is not set" in reason


def test_the_command_exits_with_the_status_and_says_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    connection = fakeredis.FakeStrictRedis()
    config = make_settings()
    monkeypatch.setattr(cli, "settings", config)
    monkeypatch.setattr(check_module, "redis_connection", lambda _config: connection)

    with pytest.raises(SystemExit) as unhealthy:
        cli.main(["--check"])
    assert unhealthy.value.code == UNHEALTHY
    assert "no fresh heartbeat" in capsys.readouterr().out

    Heartbeat(connection, "w-check", interval_seconds=10, ttl_seconds=45).beat()
    with pytest.raises(SystemExit) as healthy:
        cli.main(["--check"])
    assert healthy.value.code == HEALTHY
    assert "is alive" in capsys.readouterr().out


def test_the_flag_is_parsed_and_off_by_default() -> None:
    assert cli.parse_args(["--check"]).check is True
    assert cli.parse_args([]).check is False


def test_the_real_command_fails_fast_and_quietly_without_a_worker() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sanket.worker", "--check"],
        env={
            **os.environ,
            "DATABASE_URL": URL,
            "REDIS_URL": REDIS_URL,
            "REDIS_TIMEOUT_SECONDS": "0.5",
            "ENVIRONMENT": "development",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == UNHEALTHY
    assert "Traceback" not in result.stderr
    assert REDIS_PASSWORD not in result.stdout + result.stderr
