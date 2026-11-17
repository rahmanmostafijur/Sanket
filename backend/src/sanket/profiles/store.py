"""Database access for profiles. Every function that serves a user takes the owner and filters
by it, so a profile of another owner is simply not found. Functions without an `owner_id`
(`load_profile`) are for the worker, which acts on a profile id it was given by the system.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, case, delete, func, null, select, update
from sqlalchemy.dialects.postgresql import insert

from sanket.embeddings.client import EmbeddingSpec
from sanket.models import EmbeddingStatus, Profile, ProfileEmbedding

MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class ProfileRow:
    id: int
    owner_id: str
    name: str
    criteria: dict[str, Any]
    active: bool
    search_text: str
    content_hash: str
    embedding_status: str
    embedding_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProfileValues:
    """What is written when a profile is created or replaced."""

    name: str
    criteria: dict[str, Any]
    active: bool
    search_text: str
    content_hash: str


def _row(row: Any) -> ProfileRow:
    return ProfileRow(**row._mapping)


def insert_profile(conn: Connection, owner_id: str, values: ProfileValues) -> ProfileRow | None:
    """Insert, or return None when the owner already has a profile with that name."""
    stmt = (
        insert(Profile)
        .values(
            owner_id=owner_id,
            name=values.name,
            criteria=values.criteria,
            active=values.active,
            search_text=values.search_text,
            content_hash=values.content_hash,
        )
        .on_conflict_do_nothing(index_elements=[Profile.owner_id, Profile.name])
        .returning(*Profile.__table__.c)
    )
    row = conn.execute(stmt).one_or_none()
    return None if row is None else _row(row)


def get_profile(conn: Connection, owner_id: str, profile_id: int) -> ProfileRow | None:
    stmt = select(Profile).where(Profile.id == profile_id, Profile.owner_id == owner_id)
    row = conn.execute(stmt).one_or_none()
    return None if row is None else _row(row)


def get_profile_by_name(conn: Connection, owner_id: str, name: str) -> ProfileRow | None:
    stmt = select(Profile).where(Profile.owner_id == owner_id, Profile.name == name)
    row = conn.execute(stmt).one_or_none()
    return None if row is None else _row(row)


def list_profiles(conn: Connection, owner_id: str, limit: int) -> list[ProfileRow]:
    stmt = select(Profile).where(Profile.owner_id == owner_id).order_by(Profile.id).limit(limit)
    return [_row(row) for row in conn.execute(stmt)]


def count_profiles(conn: Connection, owner_id: str) -> int:
    stmt = select(func.count()).select_from(Profile).where(Profile.owner_id == owner_id)
    return int(conn.execute(stmt).scalar_one())


def lock_owner(conn: Connection, owner_id: str) -> None:
    """Serialise changes of one owner's profile set for the rest of the transaction, so two
    concurrent creates cannot both pass the profile limit."""
    conn.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"profile-owner:{owner_id}"))))


def replace_profile(
    conn: Connection, owner_id: str, profile_id: int, values: ProfileValues
) -> ProfileRow | None:
    """Overwrite a profile. A changed `content_hash` puts it back to `pending`: its embedding
    is stale until the worker has embedded the new content. Returns None if it is not the
    owner's. Raises IntegrityError when the new name belongs to another profile of the owner.
    """
    changed = Profile.content_hash != values.content_hash
    stmt = (
        update(Profile)
        .where(Profile.id == profile_id, Profile.owner_id == owner_id)
        .values(
            name=values.name,
            criteria=values.criteria,
            active=values.active,
            search_text=values.search_text,
            content_hash=values.content_hash,
            embedding_status=case(
                (changed, EmbeddingStatus.PENDING), else_=Profile.embedding_status
            ),
            embedding_error=case((changed, null()), else_=Profile.embedding_error),
            updated_at=func.now(),
        )
        .returning(*Profile.__table__.c)
    )
    row = conn.execute(stmt).one_or_none()
    return None if row is None else _row(row)


def delete_profile(conn: Connection, owner_id: str, profile_id: int) -> bool:
    stmt = delete(Profile).where(Profile.id == profile_id, Profile.owner_id == owner_id)
    return bool(conn.execute(stmt).rowcount)


# -- worker side -----------------------------------------------------------------------------


def load_profile(conn: Connection, profile_id: int) -> ProfileRow | None:
    row = conn.execute(select(Profile).where(Profile.id == profile_id)).one_or_none()
    return None if row is None else _row(row)


def stored_embedding_hash(conn: Connection, profile_id: int, spec: EmbeddingSpec) -> str | None:
    stmt = select(ProfileEmbedding.content_hash).where(
        ProfileEmbedding.profile_id == profile_id,
        ProfileEmbedding.model_name == spec.model_name,
        ProfileEmbedding.model_version == spec.model_version,
    )
    return conn.execute(stmt).scalar_one_or_none()


def write_embedding(
    conn: Connection,
    profile_id: int,
    spec: EmbeddingSpec,
    content_hash: str,
    embedding: Sequence[float],
) -> None:
    stmt = insert(ProfileEmbedding).values(
        profile_id=profile_id,
        model_name=spec.model_name,
        model_version=spec.model_version,
        dimension=spec.dimensions,
        content_hash=content_hash,
        embedding=list(embedding),
    )
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                ProfileEmbedding.profile_id,
                ProfileEmbedding.model_name,
                ProfileEmbedding.model_version,
            ],
            set_={
                "dimension": stmt.excluded.dimension,
                "content_hash": stmt.excluded.content_hash,
                "embedding": stmt.excluded.embedding,
                "updated_at": func.now(),
            },
        )
    )


def mark_embedding(
    conn: Connection,
    profile_id: int,
    profile_hash: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Set the embedding status of the profile, but only while it still has the content that
    was embedded (`profile_hash`): a save made meanwhile keeps its `pending`."""
    stmt = (
        update(Profile)
        .where(Profile.id == profile_id, Profile.content_hash == profile_hash)
        .values(
            embedding_status=status, embedding_error=(error or None) and error[:MAX_ERROR_CHARS]
        )
    )
    return bool(conn.execute(stmt).rowcount)


def profiles_needing_embedding(
    conn: Connection, spec: EmbeddingSpec, limit: int
) -> list[tuple[int, str]]:
    """`(id, content_hash)` of profiles that are not `ready`, or have no embedding for `spec`
    (a new model version), oldest first."""
    embedded = (
        select(ProfileEmbedding.id)
        .where(
            ProfileEmbedding.profile_id == Profile.id,
            ProfileEmbedding.model_name == spec.model_name,
            ProfileEmbedding.model_version == spec.model_version,
        )
        .exists()
    )
    stmt = (
        select(Profile.id, Profile.content_hash)
        .where((Profile.embedding_status != EmbeddingStatus.READY) | ~embedded)
        .order_by(Profile.id)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in conn.execute(stmt)]
