import os

import pytest
from sqlalchemy import create_engine, select

from sanket.models import Base, Posting
from sanket.sources.base import NormalizedPosting
from sanket.storage import save_postings, to_row

TEST_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def test_engine():
    engine = create_engine(TEST_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_upsert_keeps_one_row_and_saves_fields(test_engine) -> None:
    posting = NormalizedPosting(
        source="remoteok",
        source_id="1",
        url="https://example.com/jobs/1",
        title="Backend Developer",
        raw={"id": 1},
        company="Acme",
        location="Remote",
    )
    rows = [to_row(posting)]

    save_postings(rows, test_engine)
    save_postings(rows, test_engine)

    with test_engine.connect() as conn:
        found = conn.execute(select(Posting)).all()
    assert len(found) == 1
    assert found[0].title == "Backend Developer"
    assert found[0].company == "Acme"