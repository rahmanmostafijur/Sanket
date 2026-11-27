"""add the career profile and its sections

Revision ID: a7d3c91b5e02
Revises: 8c3d1e5f2a47
Create Date: 2026-11-28 18:00:00.000000

The personal info that 8c3d1e5f2a47 put on `users` moves into `career_profile`, which becomes its
one home: the values are copied across, then the four columns are dropped. The sections of the
career profile (education, experience, skills, languages, certifications, projects) are tables of
their own, each row owned by a user and deleted with the account.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3c91b5e02"
down_revision: str | Sequence[str] | None = "8c3d1e5f2a47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AVAILABILITIES = ("immediately", "within_one_month", "open_to_offers", "not_looking")
SKILL_LEVELS = ("beginner", "intermediate", "advanced", "expert")
PROFICIENCIES = ("basic", "conversational", "fluent", "native")
USER_COLUMNS = (("full_name", 100), ("headline", 120), ("location", 100), ("summary", 600))


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _user_id() -> sa.Column:
    return sa.Column("user_id", sa.Uuid(), nullable=False)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _owned(table: str) -> list[sa.Constraint]:
    """Primary key and the foreign key to the owner."""
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
        ),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "career_profile",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=True),
        sa.Column("headline", sa.String(length=120), nullable=True),
        sa.Column("summary", sa.String(length=1000), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("github_url", sa.String(length=300), nullable=True),
        sa.Column("linkedin_url", sa.String(length=300), nullable=True),
        sa.Column("portfolio_url", sa.String(length=300), nullable=True),
        sa.Column("availability", sa.String(length=20), nullable=True),
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
            _one_of("availability", AVAILABILITIES),
            name=op.f("ck_career_profile_availability_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_career_profile_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_career_profile")),
    )

    op.create_table(
        "career_education",
        _id(),
        _user_id(),
        sa.Column("institution", sa.String(length=150), nullable=False),
        sa.Column("degree", sa.String(length=100), nullable=True),
        sa.Column("field", sa.String(length=100), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("grade", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_career_education_dates_ordered"),
        ),
        *_owned("career_education"),
    )
    op.create_index(op.f("ix_career_education_user_id"), "career_education", ["user_id"])

    op.create_table(
        "career_experience",
        _id(),
        _user_id(),
        sa.Column("company", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.CheckConstraint(
            "(is_current AND end_date IS NULL) OR "
            "(NOT is_current AND end_date IS NOT NULL AND end_date >= start_date)",
            name=op.f("ck_career_experience_current_or_ended"),
        ),
        *_owned("career_experience"),
    )
    op.create_index(op.f("ix_career_experience_user_id"), "career_experience", ["user_id"])

    op.create_table(
        "career_skill",
        _id(),
        _user_id(),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            _one_of("level", SKILL_LEVELS), name=op.f("ck_career_skill_level_valid")
        ),
        *_owned("career_skill"),
    )
    op.create_index(op.f("ix_career_skill_user_id"), "career_skill", ["user_id"])
    op.create_index(
        "uq_career_skill_user_id_name_lower",
        "career_skill",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "career_language",
        _id(),
        _user_id(),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("proficiency", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            _one_of("proficiency", PROFICIENCIES), name=op.f("ck_career_language_proficiency_valid")
        ),
        *_owned("career_language"),
    )
    op.create_index(op.f("ix_career_language_user_id"), "career_language", ["user_id"])
    op.create_index(
        "uq_career_language_user_id_name_lower",
        "career_language",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "career_certification",
        _id(),
        _user_id(),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("issuer", sa.String(length=100), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=300), nullable=True),
        *_owned("career_certification"),
    )
    op.create_index(op.f("ix_career_certification_user_id"), "career_certification", ["user_id"])

    op.create_table(
        "career_project",
        _id(),
        _user_id(),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=300), nullable=True),
        *_owned("career_project"),
    )
    op.create_index(op.f("ix_career_project_user_id"), "career_project", ["user_id"])

    # The personal info moves: copied into the career profile, then dropped from `users`.
    op.execute(
        """
        INSERT INTO career_profile (user_id, full_name, headline, summary, city)
        SELECT id, full_name, headline, summary, location FROM users
        WHERE full_name IS NOT NULL OR headline IS NOT NULL OR summary IS NOT NULL
           OR location IS NOT NULL
        """
    )
    for name, _ in reversed(USER_COLUMNS):
        op.drop_column("users", name)


def downgrade() -> None:
    """Downgrade schema."""
    for name, length in USER_COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(length=length), nullable=True))
    op.execute(
        """
        UPDATE users SET full_name = c.full_name, headline = c.headline,
                         location = c.city, summary = left(c.summary, 600)
        FROM career_profile c WHERE c.user_id = users.id
        """
    )
    for table in (
        "career_project",
        "career_certification",
        "career_language",
        "career_skill",
        "career_experience",
        "career_education",
        "career_profile",
    ):
        op.drop_table(table)
