"""Profiles: what a user is looking for, and the jobs that matched it.

Every route acts for the owner given by `get_owner_id`. A profile that belongs to someone else
is answered exactly like one that does not exist (404), so ids reveal nothing. Saving a profile
stores it and queues its embedding; it is matched once `embedding_status` is `ready`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from sanket.api.deps import ApiContext, get_context, get_owner_id
from sanket.api.profile_schemas import (
    DEFAULT_MATCH_PAGE,
    MAX_MATCH_PAGE,
    MatchList,
    ProfileList,
    ProfileOut,
    ProfilePatch,
)
from sanket.matching.matches import list_matches
from sanket.profiles import service
from sanket.profiles.criteria import ProfileWrite

router = APIRouter(prefix="/profiles", tags=["profiles"])

Context = Annotated[ApiContext, Depends(get_context)]
Owner = Annotated[str, Depends(get_owner_id)]


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "profile not found")


@router.post(
    "",
    response_model=ProfileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a profile",
    description=(
        "Stores the profile and queues its embedding. Creating the same name with the same "
        "content again returns the stored profile (200), the same name with different content "
        "is a conflict (409), so a client may safely retry."
    ),
    responses={200: {"description": "An identical profile already existed."}},
)
def create_profile(
    body: ProfileWrite, response: Response, context: Context, owner: Owner
) -> ProfileOut:
    try:
        saved = service.create_profile(
            owner,
            body,
            queue=context.task_queue,
            max_profiles=context.max_profiles_per_owner,
            db_engine=context.db_engine,
        )
    except service.ProfileNameTakenError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a profile with this name and different content exists"
        ) from None
    except service.ProfileLimitError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    if not saved.created:
        response.status_code = status.HTTP_200_OK
    return ProfileOut.from_row(saved.profile)


@router.get("", response_model=ProfileList, summary="List your profiles")
def list_profiles(context: Context, owner: Owner) -> ProfileList:
    rows = service.list_for_owner(owner, context.db_engine)
    return ProfileList(items=[ProfileOut.from_row(row) for row in rows])


@router.get("/{profile_id}", response_model=ProfileOut, summary="Get a profile")
def get_profile(profile_id: int, context: Context, owner: Owner) -> ProfileOut:
    try:
        return ProfileOut.from_row(service.get(owner, profile_id, context.db_engine))
    except service.ProfileNotFoundError:
        raise _not_found() from None


@router.put(
    "/{profile_id}",
    response_model=ProfileOut,
    summary="Replace a profile",
    description="Replaces every field. Saving what is stored changes nothing and queues nothing.",
)
def replace_profile(
    profile_id: int, body: ProfileWrite, context: Context, owner: Owner
) -> ProfileOut:
    try:
        row = service.replace(
            owner, profile_id, body, queue=context.task_queue, db_engine=context.db_engine
        )
    except service.ProfileNotFoundError:
        raise _not_found() from None
    except service.ProfileNameTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "another profile has this name") from None
    return ProfileOut.from_row(row)


@router.patch(
    "/{profile_id}",
    response_model=ProfileOut,
    summary="Change some fields of a profile",
    description="Only the fields sent change; the result must be a valid profile as a whole.",
)
def patch_profile(
    profile_id: int, body: ProfilePatch, context: Context, owner: Owner
) -> ProfileOut:
    try:
        row = service.patch(
            owner,
            profile_id,
            body.changes(),
            queue=context.task_queue,
            db_engine=context.db_engine,
        )
    except service.ProfileNotFoundError:
        raise _not_found() from None
    except service.ProfileNameTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "another profile has this name") from None
    except service.ProfileInvalidError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.errors) from None
    return ProfileOut.from_row(row)


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a profile",
    description="Deletes the profile with its embedding and its matches. This cannot be undone.",
)
def delete_profile(profile_id: int, context: Context, owner: Owner) -> Response:
    try:
        service.delete(owner, profile_id, context.db_engine)
    except service.ProfileNotFoundError:
        raise _not_found() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{profile_id}/matches",
    response_model=MatchList,
    summary="List the matches of a profile",
    description=(
        "Oldest first, by match id: pass the last id you saw as `after_id` to get what came "
        "after it, without gaps or repeats. Withdrawn matches (jobs that stopped fitting or "
        "closed) are left out unless `include_withdrawn` is true."
    ),
)
def list_profile_matches(
    profile_id: int,
    context: Context,
    owner: Owner,
    after_id: Annotated[int, Query(ge=0, description="Only matches with a greater id.")] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_MATCH_PAGE)] = DEFAULT_MATCH_PAGE,
    include_withdrawn: bool = False,
) -> MatchList:
    try:
        service.get(owner, profile_id, context.db_engine)
    except service.ProfileNotFoundError:
        raise _not_found() from None
    page = list_matches(
        profile_id,
        after_id=after_id,
        limit=limit,
        include_withdrawn=include_withdrawn,
        db_engine=context.db_engine,
    )
    return MatchList.from_page(page)
