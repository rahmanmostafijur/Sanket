"""Authentication: who a request is, as an owner id (see docs/adr/0008-authentication.md)."""

from sanket.auth.authenticator import Authenticator, authenticator_from_settings
from sanket.auth.errors import AuthError, ForbiddenError, UnauthenticatedError
from sanket.auth.principal import Principal

__all__ = [
    "AuthError",
    "Authenticator",
    "ForbiddenError",
    "Principal",
    "UnauthenticatedError",
    "authenticator_from_settings",
]
