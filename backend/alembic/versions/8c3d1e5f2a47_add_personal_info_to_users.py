"""add personal info to users

Revision ID: 8c3d1e5f2a47
Revises: 5f2a9c4e7b1d
Create Date: 2026-11-28 12:00:00.000000

Full name, headline, location and a short summary of the person. All nullable, so existing
accounts keep working and simply have no personal info yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c3d1e5f2a47"
down_revision: str | Sequence[str] | None = "5f2a9c4e7b1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("full_name", 100),
    ("headline", 120),
    ("location", 100),
    ("summary", 600),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, length in COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for name, _ in reversed(COLUMNS):
        op.drop_column("users", name)
