"""Verify bearer JWTs: a shared secret (HS256) or the identity provider's JWKS (RS256, ES256).

The accepted algorithms are fixed per key type, never taken from the token header, which rules
out algorithm confusion. Signature, expiry (`exp` is required), `nbf`, issuer and audience are
checked when configured. The subject becomes the owner id.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from sanket.auth.errors import ForbiddenError, UnauthenticatedError
from sanket.auth.principal import Principal, checked_owner_id

logger = logging.getLogger(__name__)

SECRET_ALGORITHMS = ("HS256",)
JWKS_ALGORITHMS = ("RS256", "ES256")
MIN_SECRET_LENGTH = 32
JWKS_TIMEOUT_SECONDS = 5
JWKS_CACHE_SECONDS = 3600


class SigningKeySource(Protocol):
    """Finds the key a token was signed with."""

    def key_for(self, token: str) -> Any: ...


@dataclass(frozen=True)
class SecretKey:
    secret: str

    def key_for(self, token: str) -> Any:
        return self.secret


class JwksKeys:
    """Keys from a JWKS endpoint, cached; an unknown key id triggers one refresh."""

    def __init__(self, url: str) -> None:
        self._client = PyJWKClient(
            url, cache_keys=True, lifespan=JWKS_CACHE_SECONDS, timeout=JWKS_TIMEOUT_SECONDS
        )

    def key_for(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


@dataclass(frozen=True)
class JwtSettings:
    issuer: str | None = None
    audience: str | None = None
    leeway_seconds: int = 30
    owner_claim: str = "sub"
    required_scope: str | None = None


class JwtVerifier:
    def __init__(
        self, keys: SigningKeySource, algorithms: tuple[str, ...], settings: JwtSettings
    ) -> None:
        self._keys = keys
        self._algorithms = list(algorithms)
        self._settings = settings

    def verify(self, token: str) -> Principal:
        """The principal for a valid token; `UnauthenticatedError` or `ForbiddenError`."""
        claims = self._claims(token)
        scopes = _scopes(claims)
        required = self._settings.required_scope
        if required is not None and required not in scopes:
            raise ForbiddenError("the token does not grant access to this API")
        owner = checked_owner_id(claims.get(self._settings.owner_claim))
        return Principal(owner_id=owner, method="jwt", scopes=scopes)

    def _claims(self, token: str) -> dict[str, Any]:
        settings = self._settings
        try:
            key = self._keys.key_for(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                audience=settings.audience,
                issuer=settings.issuer,
                leeway=settings.leeway_seconds,
                options={
                    "require": ["exp"],
                    "verify_aud": settings.audience is not None,
                    "verify_iss": settings.issuer is not None,
                },
            )
        except jwt.PyJWKClientConnectionError:
            # The key source being down is our problem, not an invalid credential, but the
            # caller still cannot be identified.
            logger.warning("the JWKS endpoint is unreachable")
            raise UnauthenticatedError("the token cannot be verified right now") from None
        except jwt.InvalidTokenError as error:
            logger.info("rejected a token: %s", type(error).__name__)
            raise UnauthenticatedError("the token is invalid or expired") from None
        return claims


def _scopes(claims: dict[str, Any]) -> frozenset[str]:
    """Scopes from `scope` (space separated, OAuth) or `scp` (list or string)."""
    found: set[str] = set()
    for name in ("scope", "scp"):
        value = claims.get(name)
        if isinstance(value, str):
            found.update(value.split())
        elif isinstance(value, list):
            found.update(item for item in value if isinstance(item, str))
    return frozenset(found)
