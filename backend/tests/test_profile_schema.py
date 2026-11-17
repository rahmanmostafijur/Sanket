"""The profile, profile_embedding and job_match tables: constraints, defaults and cascades."""

from itertools import count

import pytest
from sqlalchemy import Engine, delete, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from sanket.models import EMBEDDING_COLUMN_DIMENSIONS, Job, JobMatch, Profile, ProfileEmbedding
from tests.test_index_schema import index_definition, vector
from tests.test_job_schema import add_job

_fingerprints = count(1)


def new_job(engine: Engine) -> int:
    return add_job(engine, fingerprint=f"fp1:schema-{next(_fingerprints)}")


def add_profile(engine: Engine, *, owner_id: str = "owner-1", name: str = "Backend") -> int:
    stmt = (
        insert(Profile)
        .values(
            owner_id=owner_id,
            name=name,
            criteria={"summary": "x"},
            search_text="Looking for: x",
            content_hash="h",
        )
        .returning(Profile.id)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar_one()


def add_profile_embedding(
    engine: Engine,
    profile_id: int,
    *,
    model_name: str = "model-a",
    model_version: str = "1",
    dimension: int = EMBEDDING_COLUMN_DIMENSIONS,
    embedding: list[float] | None = None,
) -> None:
    stmt = insert(ProfileEmbedding).values(
        profile_id=profile_id,
        model_name=model_name,
        model_version=model_version,
        dimension=dimension,
        content_hash="h",
        embedding=embedding if embedding is not None else vector(),
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def add_match(
    engine: Engine,
    profile_id: int,
    job_id: int,
    *,
    score: float = 0.8,
    status: str = "active",
) -> int:
    stmt = (
        insert(JobMatch)
        .values(
            profile_id=profile_id,
            job_id=job_id,
            score=score,
            components={},
            scorer_version=1,
            status=status,
            job_embedding_hash="j",
            profile_hash="p",
        )
        .returning(JobMatch.id)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar_one()


# --- profile ------------------------------------------------------------------------------


def test_a_profile_gets_defaults(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with clean_db.connect() as conn:
        row = conn.execute(select(Profile).where(Profile.id == profile_id)).one()

    assert row.active is True
    assert row.embedding_status == "pending"
    assert row.embedding_error is None
    assert row.created_at is not None and row.updated_at is not None


def test_a_name_is_unique_per_owner_only(clean_db: Engine) -> None:
    add_profile(clean_db, owner_id="a", name="Backend")
    add_profile(clean_db, owner_id="b", name="Backend")

    with pytest.raises(IntegrityError):
        add_profile(clean_db, owner_id="a", name="Backend")


def test_the_embedding_status_is_limited_to_the_known_values(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(IntegrityError), clean_db.begin() as conn:
        conn.execute(
            text("UPDATE profile SET embedding_status = 'done' WHERE id = :i"), {"i": profile_id}
        )


def test_profile_has_the_owner_listing_index(db_engine: Engine) -> None:
    names = {
        index["name"]: index["column_names"] for index in inspect(db_engine).get_indexes("profile")
    }

    assert names["ix_profile_owner_id_id"] == ["owner_id", "id"]


# --- profile_embedding --------------------------------------------------------------------


def test_profile_embedding_has_an_hnsw_cosine_index_like_job_embedding(db_engine: Engine) -> None:
    definition = index_definition(db_engine, "ix_profile_embedding_embedding_hnsw")

    assert "USING hnsw (embedding vector_cosine_ops)" in definition
    assert "m='16'" in definition
    assert "ef_construction='64'" in definition


def test_profile_embedding_column_has_the_fixed_width(db_engine: Engine) -> None:
    stmt = text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'profile_embedding'::regclass AND attname = 'embedding'"
    )
    with db_engine.connect() as conn:
        assert conn.execute(stmt).scalar_one() == EMBEDDING_COLUMN_DIMENSIONS


def test_profile_embedding_round_trips(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)
    add_profile_embedding(clean_db, profile_id, embedding=vector(0.25))

    with clean_db.connect() as conn:
        row = conn.execute(select(ProfileEmbedding)).one()

    assert row.profile_id == profile_id
    assert list(row.embedding) == pytest.approx(vector(0.25))


def test_one_embedding_per_profile_model_and_version(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)
    add_profile_embedding(clean_db, profile_id)
    add_profile_embedding(clean_db, profile_id, model_version="2")
    add_profile_embedding(clean_db, profile_id, model_name="model-b")

    with pytest.raises(IntegrityError):
        add_profile_embedding(clean_db, profile_id)


def test_profile_embedding_dimension_must_match_the_vector(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(IntegrityError):
        add_profile_embedding(clean_db, profile_id, dimension=EMBEDDING_COLUMN_DIMENSIONS - 1)


def test_profile_embedding_of_the_wrong_width_is_rejected(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(DBAPIError):
        add_profile_embedding(clean_db, profile_id, dimension=3, embedding=vector(width=3))


def test_deleting_a_profile_deletes_its_embeddings(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)
    add_profile_embedding(clean_db, profile_id)

    with clean_db.begin() as conn:
        conn.execute(delete(Profile).where(Profile.id == profile_id))

    with clean_db.connect() as conn:
        assert conn.execute(select(ProfileEmbedding.id)).all() == []


# --- job_match ----------------------------------------------------------------------------


def test_a_match_gets_defaults_and_ids_only_grow(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)
    first = add_match(clean_db, profile_id, new_job(clean_db))
    second = add_match(clean_db, profile_id, new_job(clean_db))

    with clean_db.connect() as conn:
        row = conn.execute(select(JobMatch).where(JobMatch.id == first)).one()

    assert second > first
    assert row.status == "active"
    assert row.notified_at is None
    assert row.created_at is not None and row.updated_at is not None


def test_a_profile_and_job_pair_has_one_match(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)
    job_id = new_job(clean_db)
    add_match(clean_db, profile_id, job_id)

    with pytest.raises(IntegrityError):
        add_match(clean_db, profile_id, job_id)


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_a_match_score_must_be_between_zero_and_one(clean_db: Engine, score: float) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(IntegrityError):
        add_match(clean_db, profile_id, new_job(clean_db), score=score)


def test_a_match_status_is_limited_to_the_known_values(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(IntegrityError):
        add_match(clean_db, profile_id, new_job(clean_db), status="deleted")


def test_job_match_has_the_resume_and_job_indexes(db_engine: Engine) -> None:
    indexes = {
        index["name"]: index["column_names"]
        for index in inspect(db_engine).get_indexes("job_match")
    }

    assert indexes["ix_job_match_profile_id_id"] == ["profile_id", "id"]
    assert indexes["ix_job_match_job_id"] == ["job_id"]


def test_deleting_a_profile_or_a_job_deletes_its_matches(clean_db: Engine) -> None:
    keep_profile = add_profile(clean_db, name="keep")
    drop_profile = add_profile(clean_db, name="drop")
    job_a, job_b = new_job(clean_db), new_job(clean_db)
    add_match(clean_db, drop_profile, job_a)
    add_match(clean_db, keep_profile, job_a)
    add_match(clean_db, keep_profile, job_b)

    with clean_db.begin() as conn:
        conn.execute(delete(Profile).where(Profile.id == drop_profile))
    with clean_db.connect() as conn:
        assert len(conn.execute(select(JobMatch.id)).all()) == 2

    with clean_db.begin() as conn:
        conn.execute(delete(Job).where(Job.id == job_a))
    with clean_db.connect() as conn:
        assert conn.execute(select(JobMatch.job_id)).scalars().all() == [job_b]


def test_a_match_needs_an_existing_profile_and_job(clean_db: Engine) -> None:
    profile_id = add_profile(clean_db)

    with pytest.raises(IntegrityError):
        add_match(clean_db, profile_id, 999)
    with pytest.raises(IntegrityError):
        add_match(clean_db, 999, new_job(clean_db))
