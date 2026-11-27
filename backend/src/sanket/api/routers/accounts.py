"""`POST /auth/signup` and `POST /auth/login`: email and password accounts.

Both answer with an access token in the format every protected route already accepts. Both are
rate limited per client address (before the body is even read) and per email, whatever
RATE_LIMIT_ENABLED says. A wrong password and an unknown email get the same 401 with the same
message after the same work, so log-in does not reveal which emails have an account.
"""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from sanket.accounts import service
from sanket.accounts.rules import (
    MAX_EMAIL_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    is_valid_email,
    normalize_email,
)
from sanket.accounts.tokens import AccessTokens
from sanket.api.deps import ApiContext, get_context
from sanket.api.limits import client_address

router = APIRouter(prefix="/auth", tags=["auth"])

Context = Annotated[ApiContext, Depends(get_context)]

INVALID_CREDENTIALS = "invalid email or password"
EMAIL_TAKEN = "an account with this email already exists"
NOT_ENABLED = "accounts are not enabled"
RATE_LIMITED = "too many attempts, retry later"
# Room for surrounding whitespace, which is stripped before the real length check.
_RAW_EMAIL_LENGTH = MAX_EMAIL_LENGTH + 16


def _email(value: str) -> str:
    email = normalize_email(value)
    if not is_valid_email(email):
        raise ValueError("enter a valid email address")
    return email


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=_RAW_EMAIL_LENGTH)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    _check_email = field_validator("email")(_email)


class LoginIn(BaseModel):
    """No length rule beyond the maximum: a short password is simply wrong, not invalid."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=_RAW_EMAIL_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    _check_email = field_validator("email")(_email)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds the token stays valid.")
    email: str


def _hit(context: ApiContext, key: str, limit: int) -> None:
    limiter = context.auth_limiter
    if limiter is None:
        return
    decision = limiter.hit(key, limit, context.rate_limits.window_seconds)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            RATE_LIMITED,
            headers={"Retry-After": str(decision.retry_after)},
        )


def limit_by_address(request: Request, context: Context) -> None:
    address = client_address(request, context.rate_limits.trusted_proxy_hops)
    _hit(context, f"auth:ip:{address}", context.rate_limits.auth_requests)


def _limit_by_email(context: ApiContext, email: str) -> None:
    # Keyed by a digest so limiter keys (Redis included) never hold an address.
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    _hit(context, f"auth:email:{digest}", context.rate_limits.auth_email_requests)


def _tokens(context: ApiContext) -> AccessTokens:
    if context.access_tokens is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_ENABLED)
    return context.access_tokens


def _token_out(tokens: AccessTokens, account: service.Account, response: Response) -> TokenOut:
    response.headers["Cache-Control"] = "no-store"
    issued = tokens.issue(account.id, account.email)
    return TokenOut(access_token=issued.token, expires_in=issued.expires_in, email=account.email)


@router.post(
    "/signup",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description=(
        "Creates an account and signs it in. The email is stored lower-cased; the password "
        f"must be {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters. 409 when the "
        "email already has an account."
    ),
    dependencies=[Depends(limit_by_address)],
)
def sign_up(body: SignupIn, context: Context, response: Response) -> TokenOut:
    tokens = _tokens(context)
    _limit_by_email(context, body.email)
    try:
        account = service.sign_up(body.email, body.password, context.db_engine)
    except service.EmailTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, EMAIL_TAKEN) from None
    return _token_out(tokens, account, response)


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Sign in",
    description="An access token for the account. 401 for a wrong email or password alike.",
    dependencies=[Depends(limit_by_address)],
)
def log_in(body: LoginIn, context: Context, response: Response) -> TokenOut:
    tokens = _tokens(context)
    _limit_by_email(context, body.email)
    try:
        account = service.log_in(body.email, body.password, context.db_engine)
    except service.InvalidCredentialsError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return _token_out(tokens, account, response)
