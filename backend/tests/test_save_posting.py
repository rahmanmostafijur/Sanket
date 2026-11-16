from datetime import UTC, date, datetime

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


def posting_version(**overrides) -> NormalizedPosting:
    fields = {
        "source": "greenhouse",
        "source_id": "acme:1",
        "url": "https://example.com/jobs/1",
        "title": "Backend Developer",
        "raw": {"version": 1},
        "company": "Acme",
        "location": "Berlin",
        "description": "<p>Original description.</p>",
        "salary_text": "50000-60000 EUR per year",
        "published_at": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "deadline": date(2026, 2, 1),
    }
    return NormalizedPosting(**{**fields, **overrides})


def stored_posting(engine) -> Posting:
    with engine.connect() as conn:
        return conn.execute(select(Posting)).one()


def test_reingesting_a_changed_posting_updates_every_normalized_field(clean_db) -> None:
    save_postings([to_row(posting_version())], clean_db)
    changed = posting_version(
        url="https://example.com/jobs/1-renamed",
        title="Senior Backend Developer",
        raw={"version": 2},
        company="Acme Group",
        location="Munich",
        description="<p>New description.</p>",
        salary_text="70000-90000 EUR per year",
        published_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        deadline=date(2026, 4, 1),
    )

    result = save_postings([to_row(changed)], clean_db)

    stored = stored_posting(clean_db)
    assert (result.new, result.updated, result.unchanged) == (0, 1, 0)
    assert stored.url == "https://example.com/jobs/1-renamed"
    assert stored.title == "Senior Backend Developer"
    assert stored.company == "Acme Group"
    assert stored.location == "Munich"
    assert stored.description == "<p>New description.</p>"
    assert stored.salary_text == "70000-90000 EUR per year"
    assert stored.published_at == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    assert stored.deadline == date(2026, 4, 1)
    assert stored.raw == {"version": 2}
    assert stored.content_hash == to_row(changed)["content_hash"]


def test_reingesting_clears_fields_the_source_no_longer_has(clean_db) -> None:
    save_postings([to_row(posting_version())], clean_db)
    stripped = posting_version(
        company=None,
        location=None,
        description=None,
        salary_text=None,
        published_at=None,
        deadline=None,
    )

    save_postings([to_row(stripped)], clean_db)

    stored = stored_posting(clean_db)
    assert stored.company is None
    assert stored.location is None
    assert stored.description is None
    assert stored.salary_text is None
    assert stored.published_at is None
    assert stored.deadline is None


def test_reingesting_an_unchanged_posting_keeps_updated_at(clean_db) -> None:
    save_postings([to_row(posting_version())], clean_db)
    before = stored_posting(clean_db)

    result = save_postings([to_row(posting_version())], clean_db)

    after = stored_posting(clean_db)
    assert result.unchanged == 1
    assert after.updated_at == before.updated_at
    assert after.last_seen_at > before.last_seen_at
