"""bring posting_extraction to extraction spec

Revision ID: 409e2e5f3819
Revises: 6c2f0ab0e0d7
Create Date: 2026-11-12 02:38:00.887353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '409e2e5f3819'
down_revision: Union[str, Sequence[str], None] = '6c2f0ab0e0d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "posting_extraction"
OLD_UNIQUE = "uq_posting_extraction_posting_id_content_hash_model"
NEW_UNIQUE = "uq_posting_extraction_posting_id_schema_version_prompt_version"
STATUS_CHECK = "ck_posting_extraction_status_valid"
OK_DATA_CHECK = "ck_posting_extraction_ok_has_data"


def _refuse_if_rows_would_break_constraints() -> None:
    """Existing rows become schema/prompt version 1. Stop rather than delete or rewrite
    rows if they would violate the new constraints; the operator decides what to keep."""
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(f"SELECT posting_id FROM {TABLE} GROUP BY posting_id HAVING count(*) > 1 LIMIT 5")
    ).scalars().all()
    if duplicates:
        raise RuntimeError(
            f"{TABLE} has several rows for posting ids {duplicates}; keep one row per posting "
            "before running this migration"
        )
    invalid = conn.execute(
        sa.text(
            f"SELECT count(*) FROM {TABLE} "
            "WHERE status NOT IN ('ok', 'failed') OR (status = 'ok' AND data IS NULL)"
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(f"{TABLE} has {invalid} rows with an invalid status or missing data")


def upgrade() -> None:
    """Upgrade schema."""
    _refuse_if_rows_would_break_constraints()

    # Existing rows were produced by the first schema and prompt, recorded as version 1.
    op.add_column(TABLE, sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column(TABLE, sa.Column("prompt_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column(TABLE, sa.Column("attempts", sa.Integer(), server_default="1", nullable=False))
    op.add_column(TABLE, sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    # The defaults only backfill existing rows; new rows always set these explicitly.
    op.alter_column(TABLE, "schema_version", server_default=None)
    op.alter_column(TABLE, "prompt_version", server_default=None)
    op.alter_column(TABLE, "attempts", server_default=None)
    op.alter_column(TABLE, "error", new_column_name="last_error")

    op.drop_constraint(op.f(OLD_UNIQUE), TABLE, type_="unique")
    op.create_unique_constraint(
        op.f(NEW_UNIQUE), TABLE, ["posting_id", "schema_version", "prompt_version"]
    )
    op.create_check_constraint(op.f(STATUS_CHECK), TABLE, "status IN ('ok', 'failed')")
    op.create_check_constraint(op.f(OK_DATA_CHECK), TABLE, "status <> 'ok' OR data IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(OK_DATA_CHECK), TABLE, type_="check")
    op.drop_constraint(op.f(STATUS_CHECK), TABLE, type_="check")
    op.drop_constraint(op.f(NEW_UNIQUE), TABLE, type_="unique")
    # The old table had no versions; only rows from the first schema and prompt fit it.
    op.execute(f"DELETE FROM {TABLE} WHERE schema_version <> 1 OR prompt_version <> 1")
    op.create_unique_constraint(op.f(OLD_UNIQUE), TABLE, ["posting_id", "content_hash", "model"])
    op.alter_column(TABLE, "last_error", new_column_name="error")
    op.drop_column(TABLE, "updated_at")
    op.drop_column(TABLE, "output_tokens")
    op.drop_column(TABLE, "input_tokens")
    op.drop_column(TABLE, "attempts")
    op.drop_column(TABLE, "prompt_version")
    op.drop_column(TABLE, "schema_version")
