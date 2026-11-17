"""Short-lived signed tokens for the match stream.

A browser `EventSource` cannot send an `Authorization` header, so a client that holds a bearer
token asks `POST /auth/stream-token` for one of these and opens the stream with
`?stream_token=...`. The token is bound to one owner and to one request path, expires in about
a minute and is signed with HMAC-SHA256, so a token seen in a browser history or a proxy log
opens nothing but that one stream, briefly. The access log never records the query string.

Format: `v1.<payload>.<signature>`, both parts base64url without padding; the payload is JSON
`{"sub": owner, "path": path, "exp": unix seconds}`.
"""

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

from sanket.auth.errors import UnauthenticatedError
from sanket.auth.principal import Principal, checked_owner_id

VERSION = "v1"
QUERY_PARAMETER = "stream_token"
MIN_SECRET_LENGTH = 32
FEED_PATH_TEMPLATE = "/profiles/{profile_id}/matches/stream"

Clock = Callable[[], float]


def feed_path(profile_id: int) -> str:
    return FEED_PATH_TEMPLATE.format(profile_id=profile_id)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class StreamTokens:
    def __init__(self, secret: str, ttl_seconds: int = 60, clock: Clock = time.time) -> None:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"the stream token secret needs at least {MIN_SECRET_LENGTH} characters"
            )
        self._key = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def mint(self, owner_id: str, path: str) -> str:
        """A token for `owner_id` that is good for `path` until it expires."""
        claims = {"sub": owner_id, "path": path, "exp": int(self._clock()) + self.ttl_seconds}
        payload = _b64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
        return f"{VERSION}.{payload}.{self._sign(payload)}"

    def verify(self, token: str, path: str) -> Principal:
        """The principal a valid, unexpired token for exactly `path` names."""
        claims = self._claims(token)
        if claims.get("path") != path:
            raise UnauthenticatedError("the stream token is not valid for this stream")
        if not isinstance(claims.get("exp"), int) or claims["exp"] <= self._clock():
            raise UnauthenticatedError("the stream token has expired")
        return Principal(owner_id=checked_owner_id(claims.get("sub")), method="jwt")

    def _claims(self, token: str) -> dict[str, Any]:
        version, _, rest = token.partition(".")
        payload, _, signature = rest.partition(".")
        if version != VERSION or not payload or not signature:
            raise UnauthenticatedError("the stream token is invalid")
        if not hmac.compare_digest(self._sign(payload), signature):
            raise UnauthenticatedError("the stream token is invalid")
        try:
            claims = json.loads(_unb64(payload))
        except (binascii.Error, ValueError):
            raise UnauthenticatedError("the stream token is invalid") from None
        if not isinstance(claims, dict):
            raise UnauthenticatedError("the stream token is invalid")
        return claims

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).digest())
