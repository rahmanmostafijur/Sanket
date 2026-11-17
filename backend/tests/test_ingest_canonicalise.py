import logging

import pytest
from sqlalchemy import Engine, func, select

from sanket import ingest
from sanket.ingest import canonicalise_postings_after_ingest
from sanket.models import Job
from tests.canonical_helpers import add_posting, job_of


def job_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(Job)).scalar_one()


def test_postings_are_grouped_after_ingest(clean_db: Engine) -> None:
    first = add_posting(clean_db, source="remoteok")
    second = add_posting(clean_db, source="lever")

    canonicalise_postings_after_ingest(True, clean_db)

    assert job_of(clean_db, first) == job_of(clean_db, second) is not None
    assert job_count(clean_db) == 1


def test_grouping_after_ingest_can_be_turned_off(clean_db: Engine) -> None:
    posting_id = add_posting(clean_db)

    canonicalise_postings_after_ingest(False, clean_db)

    assert job_of(clean_db, posting_id) is None
    assert job_count(clean_db) == 0


def test_a_canonicalisation_failure_never_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, clean_db: Engine
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("job table is missing")

    monkeypatch.setattr(ingest, "canonicalise", broken)

    with caplog.at_level(logging.ERROR, logger="sanket.ingest"):
        canonicalise_postings_after_ingest(True, clean_db)

    assert "Canonicalisation failed" in caplog.text
