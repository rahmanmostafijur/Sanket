"""What authentication raises. The API turns these into 401 and 403 responses."""


class AuthError(Exception):
    """Base class. `message` is safe to show to the caller: it never contains a credential."""

    status_code = 400
    code = "auth_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnauthenticatedError(AuthError):
    """No credential, or one that is invalid, expired or not accepted (401)."""

    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AuthError):
    """A valid identity that lacks the permission the route needs (403)."""

    status_code = 403
    code = "forbidden"
