"""`GET /me`: who the signed-in account is, for showing in the interface.

The name comes from the career profile (`PUT /career/personal` sets it), so there is one place it
is written. Only accounts have it: a credential that is not an account (an API key, the
development owner) is answered 404, so a client can tell there is nothing to show.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sanket.api.deps import NO_ACCOUNT, ApiContext, get_account_id, get_context
from sanket.career import store

router = APIRouter(prefix="/me", tags=["account"])

Context = Annotated[ApiContext, Depends(get_context)]
AccountId = Annotated[uuid.UUID, Depends(get_account_id)]


class MeOut(BaseModel):
    email: str
    full_name: str
    headline: str


@router.get("", response_model=MeOut, summary="Your account")
def get_me(context: Context, account: AccountId) -> MeOut:
    summary = store.account_summary(account, context.db_engine)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_ACCOUNT)
    email, full_name, headline = summary
    return MeOut(email=email, full_name=full_name, headline=headline)
