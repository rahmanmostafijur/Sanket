"""Shared database fixtures.

Database tests need TEST_DATABASE_URL, which must point at a throwaway local database whose
name ends in "_test", with the schema already migrated to head (`alembic upgrade head` with
DATABASE_URL set to the test URL). The tests never create or drop tables; they only empty
them between tests, so the Alembic migrations stay the single source of the schema.
"""

import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from sqlalchemy import Engine, create_engine, inspect, text

from sanket.models import Base

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
TEST_DATABASE_SUFFIX = "_test"


def check_test_database_url(url: str) -> None:
    """Refuse any URL that is not a local database named *_test."""
    parsed = urlparse(url)
    host = parsed.hostname
    database = parsed.path.lstrip("/")
    if host not in LOCAL_HOSTS:
        pytest.fail(
            f"TEST_DATABASE_URL host must be one of {sorted(LOCAL_HOSTS)}, got {host!r}",
            pytrace=False,
        )
    if not database.endswith(TEST_DATABASE_SUFFIX):
        pytest.fail(
            f"TEST_DATABASE_URL database name must end with {TEST_DATABASE_SUFFIX!r}, "
            f"got {database!r}",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    check_test_database_url(url)
    engine = create_engine(url)
    missing = set(Base.metadata.tables) - set(inspect(engine).get_table_names())
    if missing:
        engine.dispose()
        pytest.fail(
            f"Tables {sorted(missing)} are missing from the test database; "
            "run `alembic upgrade head` with DATABASE_URL set to TEST_DATABASE_URL",
            pytrace=False,
        )
    yield engine
    engine.dispose()


def _truncate_all(engine: Engine) -> None:
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def clean_db(db_engine: Engine) -> Iterator[Engine]:
    """The test engine with every table empty before and after the test.

    Truncating is used instead of a rolled-back transaction because the code under test
    opens its own connections and commits.
    """
    _truncate_all(db_engine)
    yield db_engine
    _truncate_all(db_engine)
