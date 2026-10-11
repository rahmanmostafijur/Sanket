import pytest
import os
from sqlalchemy import create_engine, select

from sanket.models import Base, Posting
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


def test_upsert_keeps_count_and_updated_at(test_engine) -> None:
    job = {"id": 1, "company": "Acme", "position": "Dev", "description": "x", "location": "Remote"}
    rows = [to_row(job, "remoteok")]

    save_postings(rows, test_engine)
    save_postings(rows, test_engine)

    with test_engine.connect() as conn:
        found = conn.execute(select(Posting)).scalars().all()
    assert len(found) == 1
