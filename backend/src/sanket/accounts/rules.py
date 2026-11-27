"""What an email address and a password must look like."""

import re

MAX_EMAIL_LENGTH = 254
MIN_PASSWORD_LENGTH = 12
# Long enough for any passphrase or manager-generated password, short enough that hashing an
# oversized input cannot be used to burn CPU.
MAX_PASSWORD_LENGTH = 128

# One "@", a non-empty local part and a dotted domain, no whitespace or control characters. The
# address is not verified by mail, so this only rejects what cannot be an address.
_EMAIL = re.compile(r"^[^\s@\x00-\x1f\x7f]{1,64}@[^\s@\x00-\x1f\x7f.]+(\.[^\s@\x00-\x1f\x7f.]+)+$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    return len(value) <= MAX_EMAIL_LENGTH and _EMAIL.match(value) is not None
