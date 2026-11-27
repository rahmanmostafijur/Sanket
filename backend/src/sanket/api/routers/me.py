"""`GET /me` and `PUT /me`: the personal info of the signed-in account.

Only accounts have it. A credential that is not an account (an API key, the development
owner) is answered 404, so a client can tell there is nothing to show.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sanket.accounts import personal
from sanket.accounts.identity import user_id_of
from sanket.accounts.personal import PersonalInfo
from sanket.api.deps import ApiContext, get_context, get_owner_id

router = APIRouter(prefix="/me", tags=["account"])

Context = Annotated[ApiContext, Depends(get_context)]
Owner = Annotated[str, Depends(get_owner_id)]

NO_ACCOUNT = "this credential has no account"


class MeOut(BaseModel):
    email: str
    full_name: str
    headline: str
    location: str
    summary: str

    @classmethod
    def of(cls, account: personal.AccountInfo) -> "MeOut":
        return cls(email=account.email, **account.personal.model_dump())


def _user_id(owner: str) -> uuid.UUID:
    user_id = user_id_of(owner)
    if user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ACCOUNT)
    return user_id


@router.get("", response_model=MeOut, summary="Your account and personal info")
def get_me(context: Context, owner: Owner) -> MeOut:
    try:
        return MeOut.of(personal.get_account(_user_id(owner), context.db_engine))
    except personal.AccountNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ACCOUNT) from None


@router.put(
    "",
    response_model=MeOut,
    summary="Replace your personal info",
    description="Sets all four fields; an empty value clears one.",
)
def put_me(body: PersonalInfo, context: Context, owner: Owner) -> MeOut:
    try:
        return MeOut.of(personal.update_personal(_user_id(owner), body, context.db_engine))
    except personal.AccountNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ACCOUNT) from None
