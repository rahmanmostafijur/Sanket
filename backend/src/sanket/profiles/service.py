"""Create, read, replace, patch and delete profiles, always for one owner.

A save stores the profile and queues an `embed_profile` task; the embedding provider is never
called here. Until the worker has embedded the content the profile is `pending` and is not
matched. A task that cannot be queued (no Redis, Redis down) is logged and does not fail the
save: the stored profile is the source of truth and `python -m sanket.matching embed-profiles`
queues or runs whatever is still pending.

Creating is idempotent: the same owner and name with the same content returns the stored
profile (and queues the embedding again if it is still pending, which repairs a lost task),
the same name with different content is a conflict.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from sanket.db import engine
from sanket.models import EmbeddingStatus
from sanket.profiles.criteria import ProfileWrite, criteria_of
from sanket.profiles.store import (
    ProfileRow,
    ProfileValues,
    count_profiles,
    delete_profile,
    get_profile,
    get_profile_by_name,
    insert_profile,
    list_profiles,
    lock_owner,
    replace_profile,
)
from sanket.profiles.text import build_profile_text, content_hash
from sanket.queue.base import TaskQueue
from sanket.queue.tasks import TASK_EMBED_PROFILE, embed_profile_key

logger = logging.getLogger(__name__)

MAX_LISTED_PROFILES = 1000


class ProfileError(Exception):
    """Base class of the errors a caller maps to a response."""


class ProfileNotFoundError(ProfileError):
    """No such profile for this owner (also when it belongs to someone else)."""


class ProfileNameTakenError(ProfileError):
    """The owner already has another profile with this name."""


class ProfileLimitError(ProfileError):
    """The owner has as many profiles as allowed."""


class ProfileInvalidError(ProfileError):
    """A patched profile does not validate."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("the profile is invalid")
        self.errors = errors


@dataclass(frozen=True)
class SavedProfile:
    profile: ProfileRow
    # False when an identical profile already existed.
    created: bool


def values_of(data: ProfileWrite) -> ProfileValues:
    """What is stored for a request body: criteria as JSON, the embedding text and the hash."""
    criteria = criteria_of(data)
    return ProfileValues(
        name=data.name,
        criteria=criteria.model_dump(mode="json"),
        active=data.active,
        search_text=build_profile_text(criteria),
        content_hash=content_hash(criteria, data.active),
    )


def schedule_embedding(queue: TaskQueue | None, profile: ProfileRow) -> bool:
    """Queue the embedding of the profile's current content; False if it could not be queued."""
    if queue is None:
        logger.warning("No task queue: profile %d stays pending until it is embedded", profile.id)
        return False
    payload = {"profile_id": profile.id, "content_hash": profile.content_hash}
    key = embed_profile_key(profile.id, profile.content_hash)
    try:
        queue.enqueue(TASK_EMBED_PROFILE, payload, key=key)
    except Exception:  # the queue backend may fail in any way; the save must still succeed
        logger.exception("Queueing the embedding of profile %d failed", profile.id)
        return False
    return True


def create_profile(
    owner_id: str,
    data: ProfileWrite,
    *,
    queue: TaskQueue | None,
    max_profiles: int,
    db_engine: Engine = engine,
) -> SavedProfile:
    values = values_of(data)
    with db_engine.begin() as conn:
        lock_owner(conn, owner_id)
        existing = get_profile_by_name(conn, owner_id, values.name)
        if existing is None:
            if count_profiles(conn, owner_id) >= max_profiles:
                raise ProfileLimitError(f"at most {max_profiles} profiles are allowed")
            created = insert_profile(conn, owner_id, values)
            if created is None:
                raise ProfileNameTakenError(values.name)
    if existing is None:
        assert created is not None
        schedule_embedding(queue, created)
        return SavedProfile(created, True)
    if existing.content_hash != values.content_hash:
        raise ProfileNameTakenError(values.name)
    if existing.embedding_status != EmbeddingStatus.READY:
        schedule_embedding(queue, existing)
    return SavedProfile(existing, False)


def get(owner_id: str, profile_id: int, db_engine: Engine = engine) -> ProfileRow:
    with db_engine.connect() as conn:
        profile = get_profile(conn, owner_id, profile_id)
    if profile is None:
        raise ProfileNotFoundError(profile_id)
    return profile


def list_for_owner(owner_id: str, db_engine: Engine = engine) -> list[ProfileRow]:
    with db_engine.connect() as conn:
        return list_profiles(conn, owner_id, MAX_LISTED_PROFILES)


def replace(
    owner_id: str,
    profile_id: int,
    data: ProfileWrite,
    *,
    queue: TaskQueue | None,
    db_engine: Engine = engine,
) -> ProfileRow:
    """Replace everything but the id. Saving what is stored changes and queues nothing."""
    values = values_of(data)
    try:
        with db_engine.begin() as conn:
            lock_owner(conn, owner_id)
            current = get_profile(conn, owner_id, profile_id)
            if current is None:
                raise ProfileNotFoundError(profile_id)
            if (current.name, current.content_hash) == (values.name, values.content_hash):
                saved = current
            else:
                replaced = replace_profile(conn, owner_id, profile_id, values)
                if replaced is None:
                    raise ProfileNotFoundError(profile_id)
                saved = replaced
    except IntegrityError as error:
        raise ProfileNameTakenError(values.name) from error
    if (
        saved.content_hash != current.content_hash
        or saved.embedding_status != EmbeddingStatus.READY
    ):
        schedule_embedding(queue, saved)
    return saved


def patch(
    owner_id: str,
    profile_id: int,
    changes: Mapping[str, Any],
    *,
    queue: TaskQueue | None,
    db_engine: Engine = engine,
) -> ProfileRow:
    """Replace only the fields in `changes`; the result must validate as a whole."""
    current = get(owner_id, profile_id, db_engine)
    merged = {
        "name": current.name,
        "active": current.active,
        **current.criteria,
        **changes,
    }
    try:
        data = ProfileWrite.model_validate(merged)
    except ValidationError as error:
        details = [dict(item) for item in error.errors(include_url=False, include_context=False)]
        raise ProfileInvalidError(details) from error
    return replace(owner_id, profile_id, data, queue=queue, db_engine=db_engine)


def delete(owner_id: str, profile_id: int, db_engine: Engine = engine) -> None:
    """Delete the profile, its embeddings and its matches."""
    with db_engine.begin() as conn:
        if not delete_profile(conn, owner_id, profile_id):
            raise ProfileNotFoundError(profile_id)
