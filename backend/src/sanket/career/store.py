"""Reading and writing the career profile.

Every function takes the owner's user id and touches only rows that carry it, so one account can
never read or change another's data: a row of someone else is simply not found. A section is
replaced in one transaction, and the rows of a deleted account go with it (foreign keys cascade).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from sanket.career import schemas
from sanket.career.sections import (
    CERTIFICATIONS,
    EDUCATION,
    EXPERIENCE,
    LANGUAGES,
    PROJECTS,
    SKILLS,
    SectionSpec,
)
from sanket.models import CareerProfile, User

UNIQUE_INDEX_PREFIX = "uq_career_"


class SectionFullError(Exception):
    """The section already holds as many entries as it may."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"this section can hold at most {limit} entries")
        self.limit = limit


class DuplicateEntryError(Exception):
    """Two entries of the section would have the same name."""


class EntryNotFoundError(Exception):
    """No such entry among the owner's own."""


@dataclass(frozen=True)
class CareerData:
    personal: schemas.PersonalWrite
    education: list[schemas.EducationOut]
    experience: list[schemas.ExperienceOut]
    skills: list[schemas.SkillOut]
    languages: list[schemas.LanguageOut]
    certifications: list[schemas.CertificationOut]
    projects: list[schemas.ProjectOut]


def _personal_of(row: Any) -> schemas.PersonalWrite:
    if row is None:
        return schemas.PersonalWrite()
    return schemas.PersonalWrite(
        full_name=row.full_name or "",
        headline=row.headline or "",
        summary=row.summary or "",
        country=row.country or "",
        city=row.city or "",
        github_url=row.github_url or "",
        linkedin_url=row.linkedin_url or "",
        portfolio_url=row.portfolio_url or "",
        availability=row.availability,
    )


def _items(conn: Connection, spec: SectionSpec[Any, Any], user_id: uuid.UUID) -> list[Any]:
    table: Any = spec.table
    stmt = select(table).where(table.user_id == user_id).order_by(*spec.order)
    return [spec.to_out(row) for row in conn.execute(stmt)]


def load_career(user_id: uuid.UUID, db_engine: Engine) -> CareerData:
    """Everything the owner has saved; a brand-new account has all-empty data."""
    with db_engine.connect() as conn:
        personal = conn.execute(
            select(CareerProfile).where(CareerProfile.user_id == user_id)
        ).one_or_none()
        return CareerData(
            personal=_personal_of(personal),
            education=_items(conn, EDUCATION, user_id),
            experience=_items(conn, EXPERIENCE, user_id),
            skills=_items(conn, SKILLS, user_id),
            languages=_items(conn, LANGUAGES, user_id),
            certifications=_items(conn, CERTIFICATIONS, user_id),
            projects=_items(conn, PROJECTS, user_id),
        )


def save_personal(
    user_id: uuid.UUID, personal: schemas.PersonalWrite, db_engine: Engine
) -> schemas.PersonalWrite:
    """Replace every personal field (created on first save); empty values are stored as null."""
    values = {name: (value or None) for name, value in personal.model_dump().items()}
    stmt = (
        pg_insert(CareerProfile)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[CareerProfile.user_id], set_={**values, "updated_at": func.now()}
        )
        .returning(CareerProfile)
    )
    with db_engine.begin() as conn:
        return _personal_of(conn.execute(stmt).one())


def account_summary(user_id: uuid.UUID, db_engine: Engine) -> tuple[str, str, str] | None:
    """The account's email, display name and headline, or None if the account is gone."""
    stmt = (
        select(User.email, CareerProfile.full_name, CareerProfile.headline)
        .select_from(User)
        .outerjoin(CareerProfile, CareerProfile.user_id == User.id)
        .where(User.id == user_id)
    )
    with db_engine.connect() as conn:
        row = conn.execute(stmt).one_or_none()
    if row is None:
        return None
    return row.email, row.full_name or "", row.headline or ""


# --- the list sections ------------------------------------------------------------------------


def _is_duplicate(error: IntegrityError) -> bool:
    """Whether the error is a clash of names (our unique indexes) and not something else."""
    name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return isinstance(name, str) and name.startswith(UNIQUE_INDEX_PREFIX)


def list_entries(spec: SectionSpec[Any, Any], user_id: uuid.UUID, db_engine: Engine) -> list[Any]:
    with db_engine.connect() as conn:
        return _items(conn, spec, user_id)


def replace_entries(
    spec: SectionSpec[Any, Any], user_id: uuid.UUID, entries: list[Any], db_engine: Engine
) -> list[Any]:
    """The owner's whole section replaced by `entries`, all or nothing."""
    table: Any = spec.table
    try:
        with db_engine.begin() as conn:
            conn.execute(delete(table).where(table.user_id == user_id))
            if entries:
                conn.execute(
                    insert(table),
                    [{"user_id": user_id, **spec.to_values(entry)} for entry in entries],
                )
            return _items(conn, spec, user_id)
    except IntegrityError as error:
        if _is_duplicate(error):
            raise DuplicateEntryError(spec.duplicate_message) from None
        raise


def create_entry(
    spec: SectionSpec[Any, Any], user_id: uuid.UUID, entry: Any, db_engine: Engine
) -> Any:
    table: Any = spec.table
    try:
        with db_engine.begin() as conn:
            count = conn.execute(
                select(func.count()).select_from(table).where(table.user_id == user_id)
            ).scalar_one()
            if count >= spec.max_items:
                raise SectionFullError(spec.max_items)
            row = conn.execute(
                insert(table)
                .values(user_id=user_id, **spec.to_values(entry))
                .returning(*table.__table__.c)
            ).one()
            return spec.to_out(row)
    except IntegrityError as error:
        if _is_duplicate(error):
            raise DuplicateEntryError(spec.duplicate_message) from None
        raise


def update_entry(
    spec: SectionSpec[Any, Any], user_id: uuid.UUID, entry_id: int, entry: Any, db_engine: Engine
) -> Any:
    table: Any = spec.table
    stmt = (
        update(table)
        .where(table.id == entry_id, table.user_id == user_id)
        .values(**spec.to_values(entry))
        .returning(*table.__table__.c)
    )
    try:
        with db_engine.begin() as conn:
            row = conn.execute(stmt).one_or_none()
    except IntegrityError as error:
        if _is_duplicate(error):
            raise DuplicateEntryError(spec.duplicate_message) from None
        raise
    if row is None:
        raise EntryNotFoundError
    return spec.to_out(row)


def delete_entry(
    spec: SectionSpec[Any, Any], user_id: uuid.UUID, entry_id: int, db_engine: Engine
) -> None:
    table: Any = spec.table
    with db_engine.begin() as conn:
        deleted = conn.execute(
            delete(table).where(table.id == entry_id, table.user_id == user_id)
        ).rowcount
    if not deleted:
        raise EntryNotFoundError
