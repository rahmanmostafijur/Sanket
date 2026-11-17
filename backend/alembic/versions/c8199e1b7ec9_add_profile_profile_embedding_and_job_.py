"""add profile, profile_embedding and job_match tables

Revision ID: c8199e1b7ec9
Revises: c6604cea877e
Create Date: 2026-11-17 01:53:00.965258

Expand step only: three new tables, nothing existing is altered, so the code that is deployed
today keeps working and the tables stay empty until the matcher is deployed
(docs/adr/0006-profiles-and-matching.md). The vector width (768) and the HNSW parameters are
written out on purpose, as in the job_embedding migration. The `vector` extension already
exists from c6604cea877e.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8199e1b7ec9"
down_revision: str | Sequence[str] | None = "c6604cea877e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "profile",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "embedding_status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("embedding_error", sa.Text(), nullable=True),
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
            "embedding_status IN ('pending', 'ready', 'failed')",
            name=op.f("ck_profile_embedding_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile")),
        sa.UniqueConstraint("owner_id", "name", name=op.f("uq_profile_owner_id_name")),
    )
    op.create_index("ix_profile_owner_id_id", "profile", ["owner_id", "id"], unique=False)
    op.create_table(
        "job_match",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scorer_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("job_embedding_hash", sa.Text(), nullable=False),
        sa.Column("profile_hash", sa.Text(), nullable=False),
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
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'withdrawn')", name=op.f("ck_job_match_status_valid")
        ),
        sa.CheckConstraint("score >= 0 AND score <= 1", name=op.f("ck_job_match_score_in_range")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name=op.f("fk_job_match_job_id_job"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profile.id"],
            name=op.f("fk_job_match_profile_id_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_match")),
        sa.UniqueConstraint("profile_id", "job_id", name=op.f("uq_job_match_profile_id_job_id")),
    )
    op.create_index("ix_job_match_job_id", "job_match", ["job_id"], unique=False)
    op.create_index("ix_job_match_profile_id_id", "job_match", ["profile_id", "id"], unique=False)
    op.create_table(
        "profile_embedding",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
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
            name=op.f("ck_profile_embedding_dimension_matches_vector"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profile.id"],
            name=op.f("fk_profile_embedding_profile_id_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_embedding")),
        sa.UniqueConstraint(
            "profile_id",
            "model_name",
            "model_version",
            name=op.f("uq_profile_embedding_profile_id_model_name_model_version"),
        ),
    )
    op.create_index(
        "ix_profile_embedding_embedding_hnsw",
        "profile_embedding",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_profile_embedding_embedding_hnsw",
        table_name="profile_embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("profile_embedding")
    op.drop_index("ix_job_match_profile_id_id", table_name="job_match")
    op.drop_index("ix_job_match_job_id", table_name="job_match")
    op.drop_table("job_match")
    op.drop_index("ix_profile_owner_id_id", table_name="profile")
    op.drop_table("profile")
