"""Turn an `Authorization` header into a `Principal`, from the configured credential types."""

from sanket.auth.errors import UnauthenticatedError
from sanket.auth.jwt_verifier import (
    JWKS_ALGORITHMS,
    SECRET_ALGORITHMS,
    JwksKeys,
    JwtSettings,
    JwtVerifier,
    SecretKey,
)
from sanket.auth.keys import ApiKeys, parse_api_keys
from sanket.auth.principal import Principal
from sanket.config import Settings

BEARER = "bearer"
MAX_TOKEN_LENGTH = 8192


class Authenticator:
    """Accepts static API keys and JWTs. In development it can also let a caller without a
    credential in as one owner (`dev_owner`); production configuration cannot enable that.
    """

    def __init__(
        self,
        api_keys: ApiKeys | None = None,
        verifiers: tuple[JwtVerifier, ...] = (),
        dev_owner: str | None = None,
    ) -> None:
        self._api_keys = api_keys or ApiKeys()
        self._verifiers = verifiers
        self._dev_owner = dev_owner

    def authenticate(self, authorization: str | None) -> Principal:
        """The caller, or `UnauthenticatedError` / `ForbiddenError`."""
        token = _bearer_token(authorization)
        if token is None:
            if self._dev_owner is not None:
                return Principal(owner_id=self._dev_owner, method="dev")
            raise UnauthenticatedError("authentication required: send a Bearer token")
        owner = self._api_keys.owner_for(token)
        if owner is not None:
            return Principal(owner_id=owner, method="api_key")
        return self._verify_jwt(token)

    def _verify_jwt(self, token: str) -> Principal:
        failure = UnauthenticatedError("the credential is not valid")
        for verifier in self._verifiers:
            try:
                return verifier.verify(token)
            except UnauthenticatedError as error:
                failure = error
        raise failure


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != BEARER or not token or len(token) > MAX_TOKEN_LENGTH:
        raise UnauthenticatedError("the Authorization header must be: Bearer <token>")
    return token


def authenticator_from_settings(config: Settings) -> Authenticator:
    """Build the authenticator the settings describe. The settings are checked at startup by
    `sanket.runtime_checks.check_api`, so this assumes they are valid."""
    keys = ApiKeys()
    if config.auth_api_keys is not None:
        keys, _ = parse_api_keys(config.auth_api_keys.get_secret_value())
    jwt_settings = JwtSettings(
        issuer=config.auth_issuer,
        audience=config.auth_audience,
        leeway_seconds=config.auth_leeway_seconds,
        owner_claim=config.auth_owner_claim,
        required_scope=config.auth_required_scope,
    )
    verifiers: list[JwtVerifier] = []
    if config.auth_jwt_secret is not None:
        secret = SecretKey(config.auth_jwt_secret.get_secret_value())
        verifiers.append(JwtVerifier(secret, SECRET_ALGORITHMS, jwt_settings))
    if config.auth_jwks_url is not None:
        verifiers.append(JwtVerifier(JwksKeys(config.auth_jwks_url), JWKS_ALGORITHMS, jwt_settings))
    dev_owner = config.default_owner_id if dev_bypass_allowed(config) else None
    return Authenticator(keys, tuple(verifiers), dev_owner)


def dev_bypass_allowed(config: Settings) -> bool:
    """The bypass needs both the explicit flag and the development environment."""
    return config.auth_dev_bypass and config.environment == "development"
