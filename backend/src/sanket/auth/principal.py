"""The authenticated caller."""

import re
from dataclasses import dataclass
from typing import Literal

from sanket.auth.errors import UnauthenticatedError

AuthMethod = Literal["jwt", "api_key", "dev"]

MAX_OWNER_ID_LENGTH = 200
# Printable, no whitespace or control characters: owner ids end up in logs and cache keys.
_OWNER_ID = re.compile(rf"^[^\s\x00-\x1f\x7f]{{1,{MAX_OWNER_ID_LENGTH}}}$")


@dataclass(frozen=True)
class Principal:
    """Who is calling. `owner_id` scopes every owner-owned row (profiles, matches, feeds)."""

    owner_id: str
    method: AuthMethod
    scopes: frozenset[str] = frozenset()


def is_valid_owner_id(value: object) -> bool:
    return isinstance(value, str) and _OWNER_ID.match(value) is not None


def checked_owner_id(value: object) -> str:
    """The owner id, or a 401: a token whose subject cannot be an owner id is unusable."""
    if not isinstance(value, str) or not is_valid_owner_id(value):
        raise UnauthenticatedError("the token has no usable subject")
    return value
