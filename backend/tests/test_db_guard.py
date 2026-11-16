import pytest

from tests.conftest import check_test_database_url

FAILED = pytest.fail.Exception


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:5433/sanket_test",
        "postgresql+psycopg://u:p@localhost/sanket_test",
        "postgresql+psycopg://u:p@[::1]:5433/app_test",
    ],
)
def test_guard_accepts_local_test_databases(url: str) -> None:
    check_test_database_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@ep-cool-123.neon.tech/sanket_test",
        "postgresql+psycopg://u:p@10.0.0.5:5432/sanket_test",
        "postgresql+psycopg://u:p@localhost.evil.example/sanket_test",
        "postgresql+psycopg://u:p@/sanket_test",
    ],
)
def test_guard_refuses_non_local_hosts(url: str) -> None:
    with pytest.raises(FAILED, match="host"):
        check_test_database_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:5433/sanket",
        "postgresql+psycopg://u:p@127.0.0.1:5433/sanket_test_backup",
        "postgresql+psycopg://u:p@127.0.0.1:5433/",
        "postgresql+psycopg://u:p@127.0.0.1:5433",
    ],
)
def test_guard_refuses_databases_not_named_test(url: str) -> None:
    with pytest.raises(FAILED, match="database name"):
        check_test_database_url(url)
