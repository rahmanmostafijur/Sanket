"""Password hashing with argon2id (argon2-cffi's defaults, which follow RFC 9106).

`verify_password` costs the same whether or not an account exists: without a stored hash it
checks the password against a fixed dummy hash, so the response time does not reveal which
emails have an account. argon2 compares the derived hashes in constant time.
"""

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()
_DUMMY_PASSWORD = "not-a-password-of-any-account"


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _HASHER.hash(_DUMMY_PASSWORD)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Whether `password` matches `stored_hash`; always False (after the same work) without one."""
    try:
        matched = _HASHER.verify(stored_hash or _dummy_hash(), password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return matched and stored_hash is not None
