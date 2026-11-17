"""Fail-fast checks of the settings a process needs to run, made at startup.

`Settings` validates each value on its own; what a process role needs as a whole (an API in
production must have authentication configured, a worker needs the embedding key) is checked
here, so a misconfigured deployment stops at start instead of failing on the first request.
Every problem is collected and reported together. Messages name the setting, never its value.
"""

from sanket.auth.authenticator import dev_bypass_allowed
from sanket.auth.jwt_verifier import MIN_SECRET_LENGTH
from sanket.auth.keys import parse_api_keys
from sanket.auth.stream_token import MIN_SECRET_LENGTH as MIN_STREAM_SECRET_LENGTH
from sanket.config import DEV_BYPASS_IN_PRODUCTION, Settings


class ConfigError(Exception):
    """The settings do not describe a runnable process; the message lists every problem."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid configuration: " + "; ".join(problems))


def ensure_valid(problems: list[str]) -> None:
    if problems:
        raise ConfigError(problems)


def worker_problems(config: Settings) -> list[str]:
    problems: list[str] = []
    if config.is_production and config.gemini_api_key is None:
        problems.append("GEMINI_API_KEY is required in production (profile embedding needs it)")
    return problems


def check_worker(config: Settings) -> None:
    ensure_valid(worker_problems(config))


def _secret_problems(config: Settings) -> list[str]:
    problems: list[str] = []
    jwt_secret = config.auth_jwt_secret
    if jwt_secret is not None and len(jwt_secret.get_secret_value()) < MIN_SECRET_LENGTH:
        problems.append(f"AUTH_JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    stream_secret = config.auth_stream_token_secret
    if (
        stream_secret is not None
        and len(stream_secret.get_secret_value()) < MIN_STREAM_SECRET_LENGTH
    ):
        problems.append(
            f"AUTH_STREAM_TOKEN_SECRET must be at least {MIN_STREAM_SECRET_LENGTH} characters"
        )
    if config.auth_api_keys is not None:
        problems.extend(parse_api_keys(config.auth_api_keys.get_secret_value())[1])
    return problems


def _auth_problems(config: Settings) -> list[str]:
    problems = _secret_problems(config)
    if config.auth_dev_bypass and config.is_production:
        # Settings refuses this itself; kept for objects that were built without validation.
        problems.append(DEV_BYPASS_IN_PRODUCTION)
    jwks_url = config.auth_jwks_url
    insecure_jwks = jwks_url is not None and not jwks_url.startswith("https://")
    if insecure_jwks and config.environment != "development":
        problems.append("AUTH_JWKS_URL must be an https URL")
    has_credentials = bool(config.auth_jwt_secret or config.auth_jwks_url or config.auth_api_keys)
    if not has_credentials and not dev_bypass_allowed(config):
        problems.append(
            "no authentication is configured: set AUTH_JWT_SECRET, AUTH_JWKS_URL or "
            "AUTH_API_KEYS (or AUTH_DEV_BYPASS=true outside ENVIRONMENT=production)"
        )
    return problems


def api_problems(config: Settings) -> list[str]:
    return _auth_problems(config)


def check_api(config: Settings) -> None:
    ensure_valid(api_problems(config))
