"""Access tokens for signed-in users, in the format the API's JWT verifier already accepts.

They are HS256 JWTs signed with AUTH_JWT_SECRET, carrying the owner id under AUTH_OWNER_CLAIM
(`sub` by default), `iat`, `exp` and, when configured, `iss` (AUTH_ISSUER), `aud`
(AUTH_AUDIENCE) and `scope` (AUTH_REQUIRED_SCOPE). `email` is there for display only.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

from sanket.accounts.identity import owner_id_for
from sanket.config import Settings

ALGORITHM = "HS256"


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_in: int


@dataclass(frozen=True)
class AccessTokens:
    secret: str
    ttl_seconds: int
    owner_claim: str = "sub"
    issuer: str | None = None
    audience: str | None = None
    scope: str | None = None

    def issue(self, user_id: uuid.UUID, email: str, now: float | None = None) -> IssuedToken:
        issued_at = int(time.time() if now is None else now)
        claims: dict[str, Any] = {
            self.owner_claim: owner_id_for(user_id),
            "email": email,
            "iat": issued_at,
            "exp": issued_at + self.ttl_seconds,
        }
        if self.issuer is not None:
            claims["iss"] = self.issuer
        if self.audience is not None:
            claims["aud"] = self.audience
        if self.scope is not None:
            claims["scope"] = self.scope
        return IssuedToken(jwt.encode(claims, self.secret, ALGORITHM), self.ttl_seconds)


def access_tokens_from_settings(config: Settings) -> AccessTokens | None:
    """None without AUTH_JWT_SECRET: accounts then cannot sign anyone in."""
    if config.auth_jwt_secret is None:
        return None
    return AccessTokens(
        secret=config.auth_jwt_secret.get_secret_value(),
        ttl_seconds=config.auth_access_token_ttl_seconds,
        owner_claim=config.auth_owner_claim,
        issuer=config.auth_issuer,
        audience=config.auth_audience,
        scope=config.auth_required_scope,
    )
