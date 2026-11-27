"""`/career`: the signed-in account's career profile. Private: nothing here is public.

`GET /career` returns everything with its completeness. `PUT /career/personal` replaces the
personal fields. Each list section (education, experience, skills, languages, certifications,
projects) has the same routes: list, replace the whole list in one go, add one entry, change one
and remove one. `POST /career/matching-draft` proposes a matching profile and saves nothing.

Every route acts for the account of the credential and sees only that account's rows; an entry
of someone else is answered exactly like one that does not exist (404). A credential that is not
an account (an API key) is answered 404 before anything else.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import create_model

from sanket.api.deps import ApiContext, get_account_id, get_context
from sanket.career import schemas, store
from sanket.career.completeness import completeness_of, years_of_experience
from sanket.career.matching import NothingToDeriveError, derive_draft
from sanket.career.sections import ALL_SECTIONS, SectionSpec

router = APIRouter(prefix="/career", tags=["career"])

Context = Annotated[ApiContext, Depends(get_context)]
AccountId = Annotated[uuid.UUID, Depends(get_account_id)]

NOT_FOUND = "entry not found"
NOTHING_TO_DERIVE = "add a job or a skill to your career profile first"


@router.get("", response_model=schemas.CareerOut, summary="Your whole career profile")
def get_career(context: Context, account: AccountId, response: Response) -> schemas.CareerOut:
    data = store.load_career(account, context.db_engine)
    response.headers["Cache-Control"] = "no-store"
    return schemas.CareerOut(
        personal=data.personal,
        education=data.education,
        experience=data.experience,
        skills=data.skills,
        languages=data.languages,
        certifications=data.certifications,
        projects=data.projects,
        completeness=completeness_of(data),
        years_of_experience=years_of_experience(data.experience),
    )


@router.put(
    "/personal",
    response_model=schemas.PersonalWrite,
    summary="Replace your personal details",
    description="Sets every personal field; an omitted or empty one is cleared.",
)
def put_personal(
    body: schemas.PersonalWrite, context: Context, account: AccountId
) -> schemas.PersonalWrite:
    return store.save_personal(account, body, context.db_engine)


@router.post(
    "/matching-draft",
    response_model=schemas.MatchingDraftOut,
    summary="Propose a matching profile from your career profile",
    description=(
        "Roles, required and preferred skills, seniority (from the years worked) and locations, "
        "worked out from what you saved. Nothing is created: review the proposal and save a "
        "matching profile yourself. 422 when there is no job and no skill to use."
    ),
)
def matching_draft(
    context: Context, account: AccountId, response: Response
) -> schemas.MatchingDraftOut:
    try:
        draft = derive_draft(store.load_career(account, context.db_engine))
    except NothingToDeriveError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NOTHING_TO_DERIVE) from None
    response.headers["Cache-Control"] = "no-store"
    return draft


def _conflict(error: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def _section_router(spec: SectionSpec[Any, Any]) -> APIRouter:
    """The five routes of one list section. Models are the section's own, so the OpenAPI schema
    and the validation errors name its real fields."""
    write: Any = spec.write
    out: Any = spec.out
    items_body: Any = spec.items
    listing: Any = create_model(f"{spec.name.title()}List", items=(list[out], ...))
    section = APIRouter(prefix=f"/{spec.name}", tags=["career"])

    @section.get("", response_model=listing, summary=f"List your {spec.name}")
    def list_entries(context: Context, account: AccountId) -> Any:
        return listing(items=store.list_entries(spec, account, context.db_engine))

    @section.put(
        "",
        response_model=listing,
        summary=f"Replace all your {spec.name} in one go",
        description="Takes the whole list; the entries saved before are replaced. All or nothing.",
    )
    def replace_entries(body: items_body, context: Context, account: AccountId) -> Any:
        try:
            entries = store.replace_entries(spec, account, body.items, context.db_engine)
        except store.DuplicateEntryError as error:
            raise _conflict(error) from None
        return listing(items=entries)

    @section.post(
        "",
        response_model=out,
        status_code=status.HTTP_201_CREATED,
        summary=f"Add one entry to your {spec.name}",
    )
    def create_entry(body: write, context: Context, account: AccountId) -> Any:
        try:
            return store.create_entry(spec, account, body, context.db_engine)
        except (store.SectionFullError, store.DuplicateEntryError) as error:
            raise _conflict(error) from None

    @section.put("/{entry_id}", response_model=out, summary=f"Change one of your {spec.name}")
    def update_entry(
        entry_id: int,
        body: write,
        context: Context,
        account: AccountId,
    ) -> Any:
        try:
            return store.update_entry(spec, account, entry_id, body, context.db_engine)
        except store.EntryNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None
        except store.DuplicateEntryError as error:
            raise _conflict(error) from None

    @section.delete(
        "/{entry_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary=f"Remove one of your {spec.name}",
    )
    def delete_entry(entry_id: int, context: Context, account: AccountId) -> Response:
        try:
            store.delete_entry(spec, account, entry_id, context.db_engine)
        except store.EntryNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return section


for _spec in ALL_SECTIONS:
    router.include_router(_section_router(_spec))
