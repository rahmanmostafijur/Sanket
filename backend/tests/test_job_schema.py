import pytest
from sqlalchemy import Engine, delete, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError

from sanket.models import Job, Posting
from tests.factories import add_posting

FINGERPRINT = "fp1:test"


def add_job(engine: Engine, fingerprint: str = FINGERPRINT, **values: object) -> int:
    stmt = (
        insert(Job)
        .values(fingerprint=fingerprint, title="Engineer", company="Acme", **values)
        .returning(Job.id)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar_one()


def posting_job_id(engine: Engine, posting_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(select(Posting.job_id).where(Posting.id == posting_id)).scalar_one()


def test_posting_job_id_is_a_nullable_foreign_key_with_an_index(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    column = next(c for c in inspector.get_columns("posting") if c["name"] == "job_id")
    foreign_keys = {fk["name"]: fk for fk in inspector.get_foreign_keys("posting")}
    indexes = {index["name"]: index for index in inspector.get_indexes("posting")}

    assert column["nullable"] is True
    assert foreign_keys["fk_posting_job_id_job"]["referred_table"] == "job"
    assert foreign_keys["fk_posting_job_id_job"]["options"]["ondelete"] == "SET NULL"
    assert indexes["ix_posting_job_id"]["column_names"] == ["job_id"]


def test_postings_inserted_without_a_job_id_keep_working(clean_db: Engine) -> None:
    posting_id = add_posting(clean_db)

    assert posting_job_id(clean_db, posting_id) is None


def test_job_defaults(clean_db: Engine) -> None:
    job_id = add_job(clean_db)

    with clean_db.connect() as conn:
        row = conn.execute(select(Job).where(Job.id == job_id)).one()
    assert row.posting_count == 0
    assert row.representative_posting_id is None
    assert row.location is None
    assert row.first_seen_at is not None
    assert row.last_seen_at is not None
    assert row.created_at is not None
    assert row.updated_at is not None


def test_job_fingerprint_is_unique(clean_db: Engine) -> None:
    add_job(clean_db)

    with pytest.raises(IntegrityError):
        add_job(clean_db)


def test_job_posting_count_cannot_be_negative(clean_db: Engine) -> None:
    with pytest.raises(IntegrityError):
        add_job(clean_db, posting_count=-1)


def test_deleting_a_job_unlinks_its_postings(clean_db: Engine) -> None:
    job_id = add_job(clean_db)
    posting_id = add_posting(clean_db)
    with clean_db.begin() as conn:
        conn.execute(update(Posting).where(Posting.id == posting_id).values(job_id=job_id))

    with clean_db.begin() as conn:
        conn.execute(delete(Job).where(Job.id == job_id))

    assert posting_job_id(clean_db, posting_id) is None


def test_deleting_the_representative_posting_clears_the_reference(clean_db: Engine) -> None:
    posting_id = add_posting(clean_db)
    job_id = add_job(clean_db, representative_posting_id=posting_id)

    with clean_db.begin() as conn:
        conn.execute(delete(Posting).where(Posting.id == posting_id))

    with clean_db.connect() as conn:
        assert (
            conn.execute(select(Job.representative_posting_id).where(Job.id == job_id)).scalar_one()
            is None
        )
