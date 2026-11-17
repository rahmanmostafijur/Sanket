"""Static API keys: `owner=key` pairs for service callers and operators.

The configuration is a comma-separated list such as `alice=<key>,ops=<key>`. Keys are compared
through a SHA-256 digest and `hmac.compare_digest`, so timing says nothing about a key's
content, and only digests are kept in memory after parsing. Keys must be long and random
(`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
"""

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field

from sanket.auth.principal import is_valid_owner_id

MIN_API_KEY_LENGTH = 24


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
        if not separator or not is_valid_owner_id(owner):
            problems.append(f"AUTH_API_KEYS entry {number} must look like owner=key")
        elif len(key) < MIN_API_KEY_LENGTH:
            problems.append(
                f"AUTH_API_KEYS entry {number} has a key shorter than {MIN_API_KEY_LENGTH}"
            )
        elif _digest(key) in owners:
            problems.append(f"AUTH_API_KEYS entry {number} repeats a key")
        else:
            owners[_digest(key)] = owner
    return ApiKeys(owners), problems
