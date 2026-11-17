"""add job table and posting job_id

Revision ID: e67e00d6f629
Revises: 409e2e5f3819
Create Date: 2026-11-17 00:35:41.397339

Expand step only: a new table and a nullable posting.job_id. No backfill and no NOT NULL, so
code that does not know about jobs keeps working. Postings are assigned to jobs afterwards by
`python -m sanket.canonicalise --apply`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e67e00d6f629"
down_revision: str | Sequence[str] | None = "409e2e5f3819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("representative_posting_id", sa.BigInteger(), nullable=True),
        sa.Column("posting_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.CheckConstraint("posting_count >= 0", name=op.f("ck_job_posting_count_nonnegative")),
        sa.ForeignKeyConstraint(
            ["representative_posting_id"],
            ["posting.id"],
            name=op.f("fk_job_representative_posting_id_posting"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_job_fingerprint")),
    )
    op.add_column("posting", sa.Column("job_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_posting_job_id"), "posting", ["job_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_posting_job_id_job"), "posting", "job", ["job_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_posting_job_id_job"), "posting", type_="foreignkey")
    op.drop_index(op.f("ix_posting_job_id"), table_name="posting")
    op.drop_column("posting", "job_id")
    op.drop_table("job")
