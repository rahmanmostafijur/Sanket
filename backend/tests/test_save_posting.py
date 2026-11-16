from sqlalchemy import select

from sanket.models import Posting
from sanket.sources.base import NormalizedPosting
from sanket.storage import save_postings, to_row


def test_upsert_keeps_one_row_and_saves_fields(clean_db) -> None:
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

    save_postings(rows, clean_db)
    save_postings(rows, clean_db)

    with clean_db.connect() as conn:
        found = conn.execute(select(Posting)).all()
    assert len(found) == 1
    assert found[0].title == "Backend Developer"
    assert found[0].company == "Acme"
