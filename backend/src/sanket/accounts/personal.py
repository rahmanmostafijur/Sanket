"""Personal info of an account: who the person is, shared by all their profiles.

This is the one place it is stored (columns of `users`); profiles keep only what is searched
for. `full_name` is the name shown for the account. Every field is optional text: stripped,
whitespace collapsed, bounded, and a NUL character (which PostgreSQL text cannot hold) is
refused. An empty value is stored as null.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select, update

from sanket.models import User
from sanket.profiles.criteria import clean_text

MAX_FULL_NAME_CHARS = 100
MAX_HEADLINE_CHARS = 120
MAX_LOCATION_CHARS = 100
MAX_PERSONAL_SUMMARY_CHARS = 600

FullName = Annotated[str, Field(max_length=MAX_FULL_NAME_CHARS)]
Headline = Annotated[str, Field(max_length=MAX_HEADLINE_CHARS)]
Location = Annotated[str, Field(max_length=MAX_LOCATION_CHARS)]
Summary = Annotated[str, Field(max_length=MAX_PERSONAL_SUMMARY_CHARS)]


class PersonalInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: FullName = ""
    headline: Headline = ""
    location: Location = ""
    summary: Summary = ""

    @field_validator("full_name", "headline", "location", "summary")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_text(value)


@dataclass(frozen=True)
class AccountInfo:
    email: str
    personal: PersonalInfo


class AccountNotFoundError(Exception):
    """The account no longer exists."""


def _info_of(row: object) -> PersonalInfo:
    return PersonalInfo(
        full_name=getattr(row, "full_name", None) or "",
        headline=getattr(row, "headline", None) or "",
        location=getattr(row, "location", None) or "",
        summary=getattr(row, "summary", None) or "",
    )


def get_account(user_id: uuid.UUID, db_engine: Engine) -> AccountInfo:
    with db_engine.connect() as conn:
        row = conn.execute(
            select(User.email, User.full_name, User.headline, User.location, User.summary).where(
                User.id == user_id
            )
        ).one_or_none()
    if row is None:
        raise AccountNotFoundError
    return AccountInfo(row.email, _info_of(row))


def update_personal(user_id: uuid.UUID, info: PersonalInfo, db_engine: Engine) -> AccountInfo:
    """Replace the four fields; empty ones become null."""
    values = {name: value or None for name, value in info.model_dump().items()}
    with db_engine.begin() as conn:
        row = conn.execute(
            update(User)
            .where(User.id == user_id)
            .values(**values)
            .returning(User.email, User.full_name, User.headline, User.location, User.summary)
        ).one_or_none()
    if row is None:
        raise AccountNotFoundError
    return AccountInfo(row.email, _info_of(row))
