"""Create an account and check a sign-in. Emails arrive normalized and validated."""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from sanket.accounts.passwords import hash_password, verify_password
from sanket.models import User

logger = logging.getLogger(__name__)


class EmailTakenError(Exception):
    """An account with this email already exists."""


class InvalidCredentialsError(Exception):
    """No account with this email, or the wrong password: deliberately indistinguishable."""


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    email: str


def sign_up(email: str, password: str, db_engine: Engine) -> Account:
    """The new account, or `EmailTakenError`. The password is hashed before the email is
    looked at, so a taken email answers no faster than a free one."""
    password_hash = hash_password(password)
    stmt = (
        insert(User).values(email=email, password_hash=password_hash).returning(User.id, User.email)
    )
    try:
        with db_engine.begin() as conn:
            row = conn.execute(stmt).one()
    except IntegrityError:
        raise EmailTakenError from None
    logger.info("account created")
    return Account(row.id, row.email)


def log_in(email: str, password: str, db_engine: Engine) -> Account:
    """The account, or `InvalidCredentialsError` for an unknown email and a wrong password alike;
    both cost one password verification."""
    with db_engine.connect() as conn:
        row = conn.execute(
            select(User.id, User.email, User.password_hash).where(User.email == email)
        ).one_or_none()
    if not verify_password(row.password_hash if row else None, password) or row is None:
        raise InvalidCredentialsError
    return Account(row.id, row.email)
