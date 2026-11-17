"""Liveness and readiness checks.

`/healthz` answers as long as the process serves requests and touches nothing else, so an
orchestrator restarts a wedged process and never a healthy one whose database is down. `/readyz`
runs the dependency checks, each under a short timeout in its own thread, and answers 503 when
any fails, so traffic is held back until the instance can serve. The response names the failing
check but never the error (details go to the log).
"""

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from alembic.config import Config
from alembic.script import ScriptDirectory
from redis import Redis
from sqlalchemy import Engine, text

from sanket.config import Settings

logger = logging.getLogger(__name__)

CheckFn = Callable[[], None]
OK = "ok"
FAILED = "failed"
TIMEOUT = "timeout"
MAX_PARALLEL_CHECKS = 8


@dataclass(frozen=True)
class Readiness:
    ready: bool
    checks: Mapping[str, str]

    def body(self) -> dict[str, object]:
        return {"status": "ready" if self.ready else "unavailable", "checks": dict(self.checks)}


def database_check(db_engine: Engine) -> CheckFn:
    def check() -> None:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    return check


def redis_check(client: Redis) -> CheckFn:
    def check() -> None:
        client.ping()

    return check


def code_head(alembic_ini: str) -> str | None:
    """The single migration head the code ships with."""
    heads = ScriptDirectory.from_config(Config(alembic_ini)).get_heads()
    return heads[0] if len(heads) == 1 else None


def migrations_check(db_engine: Engine, alembic_ini: str) -> CheckFn:
    def check() -> None:
        expected = code_head(alembic_ini)
        with db_engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
        if expected is None or row is None or row[0] != expected:
            raise RuntimeError("the database schema is not at the migration head")

    return check


def readiness_client(config: Settings) -> Redis | None:
    """A Redis client whose timeouts are the probe's, or None when Redis is not configured."""
    if config.redis_url is None:
        return None
    return Redis.from_url(
        config.redis_url.get_secret_value(),
        socket_connect_timeout=config.readyz_timeout_seconds,
        socket_timeout=config.readyz_timeout_seconds,
    )


def checks_from_settings(config: Settings, db_engine: Engine) -> dict[str, CheckFn]:
    checks: dict[str, CheckFn] = {"database": database_check(db_engine)}
    client = readiness_client(config)
    if client is not None:
        checks["redis"] = redis_check(client)
    if config.readyz_check_migrations:
        checks["migrations"] = migrations_check(db_engine, str(config.alembic_ini_path))
    return checks


class ReadinessProbe:
    def __init__(self, checks: Mapping[str, CheckFn], timeout_seconds: float) -> None:
        self._checks = dict(checks)
        self._timeout = timeout_seconds
        self._executor = ThreadPoolExecutor(MAX_PARALLEL_CHECKS, thread_name_prefix="readyz")

    def run(self) -> Readiness:
        futures = {name: self._executor.submit(check) for name, check in self._checks.items()}
        wait(futures.values(), timeout=self._timeout)
        results = {name: self._outcome(name, future) for name, future in futures.items()}
        return Readiness(all(value == OK for value in results.values()), results)

    @staticmethod
    def _outcome(name: str, future: "Future[None]") -> str:
        if not future.done():
            future.cancel()
            logger.warning("readiness check %s timed out", name)
            return TIMEOUT
        error = future.exception()
        if error is None:
            return OK
        logger.warning("readiness check %s failed: %s", name, type(error).__name__)
        return FAILED
