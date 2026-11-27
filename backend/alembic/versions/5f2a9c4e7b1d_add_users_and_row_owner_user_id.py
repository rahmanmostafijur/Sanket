"""add users table and user_id on profile and saved_job

Revision ID: 5f2a9c4e7b1d
Revises: bc1e664ce683
Create Date: 2026-11-27 12:00:00.000000

Existing profiles and saved jobs keep their owner_id and get a null user_id, so rows of API-key
and development owners work exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f2a9c4e7b1d"
down_revision: str | Sequence[str] | None = "bc1e664ce683"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED_TABLES = ("profile", "saved_job")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lower_case")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    for table in OWNED_TABLES:
        op.add_column(table, sa.Column("user_id", sa.Uuid(), nullable=True))
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False)
        op.create_foreign_key(
            op.f(f"fk_{table}_user_id_users"),
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(OWNED_TABLES):
        op.drop_constraint(op.f(f"fk_{table}_user_id_users"), table, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)
        op.drop_column(table, "user_id")
    op.drop_table("users")
