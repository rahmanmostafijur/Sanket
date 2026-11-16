"""Indexing configuration and the startup check that the vector width matches."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, text

from sanket.config import Settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingSpec
from sanket.models import EMBEDDING_COLUMN_DIMENSIONS

# Jobs read per database round trip while looking for work.
DEFAULT_SCAN_PAGE_SIZE = 500


class DimensionMismatchError(RuntimeError):
    """The configured embedding size does not match the vector column."""


@dataclass(frozen=True)
class IndexConfig:
    spec: EmbeddingSpec
    max_description_chars: int
    embedding_batch_size: int
    # Jobs that need work handled per run; the run stops after this many.
    batch_limit: int
    # Sources whose text is never sent to the embedding provider (data-use rules, the same
    # list as EXTRACTION_EXCLUDED_SOURCES). Their jobs are still searchable by full text.
    excluded_sources: Sequence[str] = ()
    scan_page_size: int = DEFAULT_SCAN_PAGE_SIZE


def config_from_settings(config: Settings) -> IndexConfig:
    return IndexConfig(
        spec=EmbeddingSpec(
            model_name=config.embedding_model,
            model_version=config.embedding_model_version,
            dimensions=config.embedding_dimensions,
        ),
        max_description_chars=config.indexing_max_description_chars,
        embedding_batch_size=config.embedding_batch_size,
        batch_limit=config.indexing_batch_limit,
        excluded_sources=tuple(config.extraction_excluded_sources),
    )


def column_dimensions(db_engine: Engine = engine) -> int:
    """The width of `job_embedding.embedding` in the connected database."""
    stmt = text(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = to_regclass('job_embedding') AND attname = 'embedding'"
    )
    with db_engine.connect() as conn:
        width = conn.execute(stmt).scalar_one_or_none()
    if width is None:
        raise DimensionMismatchError("job_embedding.embedding does not exist: run the migrations")
    return int(width)


def check_dimensions(dimensions: int, db_engine: Engine = engine) -> None:
    """Fail fast unless `dimensions` equals the code constant and the database column.

    The constant is checked first so a wrong setting is reported without touching the
    database; the column check catches a database migrated to a different width.
    """
    if dimensions != EMBEDDING_COLUMN_DIMENSIONS:
        raise DimensionMismatchError(
            f"EMBEDDING_DIMENSIONS is {dimensions} but the vector column is "
            f"{EMBEDDING_COLUMN_DIMENSIONS} wide; changing it needs a migration and a re-embed"
        )
    found = column_dimensions(db_engine)
    if found != dimensions:
        raise DimensionMismatchError(
            f"the database column is {found} wide but EMBEDDING_DIMENSIONS is {dimensions}"
        )
