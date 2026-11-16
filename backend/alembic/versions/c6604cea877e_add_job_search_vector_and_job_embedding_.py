"""add job search vector and job embedding table

Revision ID: c6604cea877e
Revises: e67e00d6f629
Create Date: 2026-11-17 00:54:53.623369

Expand step only: a new nullable tsvector column and hash on `job` and a new table, so code
that does not know about indexing keeps working. Nothing is backfilled here; the columns and
the table are filled by `python -m sanket.indexing --apply`.

Needs the pgvector extension, so `CREATE EXTENSION IF NOT EXISTS vector` runs first. Neon
supports pgvector, but the role that runs the migration must be allowed to create the
extension (docs/indexing.md); the local and CI images (pgvector/pgvector) ship it. The
downgrade leaves the extension installed because other objects may come to depend on it.

The vector width (768) and the HNSW parameters are written out here on purpose: a migration
must not change when the application constants do.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6604cea877e"
down_revision: str | Sequence[str] | None = "e67e00d6f629"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "job_embedding",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimension = vector_dims(embedding)",
            name=op.f("ck_job_embedding_dimension_matches_vector"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_job_embedding_job_id_job"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_embedding")),
        sa.UniqueConstraint(
            "job_id",
            "model_name",
            "model_version",
            name=op.f("uq_job_embedding_job_id_model_name_model_version"),
        ),
    )
    op.create_index(
        "ix_job_embedding_embedding_hnsw",
        "job_embedding",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.add_column("job", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    op.add_column("job", sa.Column("search_hash", sa.Text(), nullable=True))
    op.create_index(
        "ix_job_search_vector", "job", ["search_vector"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_job_search_vector", table_name="job", postgresql_using="gin")
    op.drop_column("job", "search_hash")
    op.drop_column("job", "search_vector")
    op.drop_index(
        "ix_job_embedding_embedding_hnsw",
        table_name="job_embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("job_embedding")
