import pytest
from sqlalchemy import Engine, delete, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from sanket.models import EMBEDDING_COLUMN_DIMENSIONS, Job, JobEmbedding
from tests.test_job_schema import add_job

MODEL = "model-a"


def vector(value: float = 1.0, width: int = EMBEDDING_COLUMN_DIMENSIONS) -> list[float]:
    return [value] * width


def add_embedding(
    engine: Engine,
    job_id: int,
    *,
    model_name: str = MODEL,
    model_version: str = "1",
    dimension: int = EMBEDDING_COLUMN_DIMENSIONS,
    embedding: list[float] | None = None,
) -> None:
    stmt = insert(JobEmbedding).values(
        job_id=job_id,
        model_name=model_name,
        model_version=model_version,
        dimension=dimension,
        content_hash="h",
        embedding=embedding if embedding is not None else vector(),
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def index_definition(engine: Engine, name: str) -> str:
    stmt = text("SELECT indexdef FROM pg_indexes WHERE indexname = :name")
    with engine.connect() as conn:
        return conn.execute(stmt, {"name": name}).scalar_one()


def test_vector_extension_is_installed(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        found = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()

    assert found == 1


def test_job_search_columns_are_nullable(db_engine: Engine) -> None:
    columns = {c["name"]: c for c in inspect(db_engine).get_columns("job")}

    assert columns["search_vector"]["nullable"] is True
    assert columns["search_hash"]["nullable"] is True
    assert str(columns["search_vector"]["type"]) == "TSVECTOR"


def test_search_vector_has_a_gin_index(db_engine: Engine) -> None:
    definition = index_definition(db_engine, "ix_job_search_vector")

    assert "USING gin (search_vector)" in definition


def test_embedding_has_an_hnsw_cosine_index_with_explicit_parameters(db_engine: Engine) -> None:
    definition = index_definition(db_engine, "ix_job_embedding_embedding_hnsw")

    assert "USING hnsw (embedding vector_cosine_ops)" in definition
    assert "m='16'" in definition
    assert "ef_construction='64'" in definition


def test_embedding_column_has_the_fixed_width(db_engine: Engine) -> None:
    stmt = text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'job_embedding'::regclass AND attname = 'embedding'"
    )
    with db_engine.connect() as conn:
        assert conn.execute(stmt).scalar_one() == EMBEDDING_COLUMN_DIMENSIONS


def test_embedding_round_trips_and_gets_defaults(clean_db: Engine) -> None:
    job_id = add_job(clean_db)
    add_embedding(clean_db, job_id, embedding=vector(0.5))

    with clean_db.connect() as conn:
        row = conn.execute(select(JobEmbedding)).one()

    assert row.job_id == job_id
    assert list(row.embedding) == pytest.approx(vector(0.5))
    assert row.created_at is not None
    assert row.updated_at is not None


def test_one_embedding_per_job_and_model_version(clean_db: Engine) -> None:
    job_id = add_job(clean_db)
    add_embedding(clean_db, job_id)

    with pytest.raises(IntegrityError):
        add_embedding(clean_db, job_id)


def test_models_and_versions_coexist_for_a_job(clean_db: Engine) -> None:
    job_id = add_job(clean_db)

    add_embedding(clean_db, job_id)
    add_embedding(clean_db, job_id, model_version="2")
    add_embedding(clean_db, job_id, model_name="model-b")

    with clean_db.connect() as conn:
        assert len(conn.execute(select(JobEmbedding.id)).all()) == 3


def test_dimension_must_match_the_vector(clean_db: Engine) -> None:
    job_id = add_job(clean_db)

    with pytest.raises(IntegrityError):
        add_embedding(clean_db, job_id, dimension=EMBEDDING_COLUMN_DIMENSIONS - 1)


def test_vector_of_the_wrong_width_is_rejected(clean_db: Engine) -> None:
    job_id = add_job(clean_db)

    with pytest.raises(DBAPIError):
        add_embedding(clean_db, job_id, dimension=3, embedding=vector(width=3))


def test_deleting_a_job_deletes_its_embeddings(clean_db: Engine) -> None:
    job_id = add_job(clean_db)
    add_embedding(clean_db, job_id)

    with clean_db.begin() as conn:
        conn.execute(delete(Job).where(Job.id == job_id))

    with clean_db.connect() as conn:
        assert conn.execute(select(JobEmbedding.id)).all() == []


def test_embedding_requires_an_existing_job(clean_db: Engine) -> None:
    with pytest.raises(IntegrityError):
        add_embedding(clean_db, 999)
