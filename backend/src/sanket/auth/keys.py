"""Static API keys: `owner=key` pairs for service callers and operators.

The configuration is a comma-separated list such as `alice=<key>,ops=sha256:<hex digest>`.
An entry may hold the key itself or, better, only its SHA-256 digest
(`python -m sanket.auth` makes a new key and prints both), so the environment never holds a
usable key. Keys are compared through their digest and `hmac.compare_digest`, so timing says
nothing about a key's content, and only digests are kept in memory after parsing. Keys must be
long and random.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from sanket.accounts.identity import USER_OWNER_PREFIX
from sanket.auth.principal import is_valid_owner_id

MIN_API_KEY_LENGTH = 24
DIGEST_PREFIX = "sha256:"
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
NEW_KEY_BYTES = 32


def _digest(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


@dataclass(frozen=True)
class ApiKeys:
    """Digest to owner id."""

    owners_by_digest: Mapping[bytes, str] = field(default_factory=dict)

    def owner_for(self, key: str) -> str | None:
        digest = _digest(key)
        found: str | None = None
        # Compare against every entry so the time does not depend on which one matches.
        for stored, owner in self.owners_by_digest.items():
            if hmac.compare_digest(stored, digest):
                found = owner
        return found

    def __bool__(self) -> bool:
        return bool(self.owners_by_digest)


def parse_api_keys(raw: str) -> tuple[ApiKeys, list[str]]:
    """The parsed keys and the problems found (a problem never contains a key)."""
    owners: dict[bytes, str] = {}
    problems: list[str] = []
    for index, entry in enumerate(part for part in raw.split(",") if part.strip()):
        owner, separator, key = entry.strip().partition("=")
        number = index + 1
        digest, problem = _entry_digest(key)
        if not separator or not is_valid_owner_id(owner):
            problems.append(f"AUTH_API_KEYS entry {number} must look like owner=key")
        elif owner.startswith(USER_OWNER_PREFIX):
            problems.append(
                f"AUTH_API_KEYS entry {number} uses an owner starting with {USER_OWNER_PREFIX!r}, "
                "which is reserved for accounts"
            )
        elif digest is None:
            problems.append(f"AUTH_API_KEYS entry {number} {problem}")
        elif digest in owners:
            problems.append(f"AUTH_API_KEYS entry {number} repeats a key")
        else:
            owners[digest] = owner
    return ApiKeys(owners), problems


def _entry_digest(value: str) -> tuple[bytes | None, str]:
    """The digest an entry stands for, or None and why not (never quoting the value)."""
    if value.startswith(DIGEST_PREFIX):
        hexdigest = value.removeprefix(DIGEST_PREFIX).lower()
        if not DIGEST_PATTERN.match(hexdigest):
            return None, "has a sha256: digest that is not 64 hex characters"
        return bytes.fromhex(hexdigest), ""
    if len(value) < MIN_API_KEY_LENGTH:
        return None, f"has a key shorter than {MIN_API_KEY_LENGTH}"
    return _digest(value), ""


def main() -> None:
    """Print a new random key (give it to the caller) and the entry to configure (the digest)."""
    key = secrets.token_urlsafe(NEW_KEY_BYTES)
    print(f"key:   {key}")
    print(f"entry: <owner>={DIGEST_PREFIX}{_digest(key).hex()}")
