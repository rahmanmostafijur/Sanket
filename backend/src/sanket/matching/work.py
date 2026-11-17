"""Derive the pipeline's work from the database, for the `sanket.matching` commands.

Everything the queue carries can be recomputed from stored state, which is what makes the
queue a latency device and not the system of record (ADR 0005). Each function returns the
tasks (name, payload, idempotency key) that bring the stored matches in line with the stored
jobs and profiles; queueing or running them is the caller's choice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, exists, select

from sanket.embeddings.client import EmbeddingSpec
from sanket.models import (
    EmbeddingStatus,
    Job,
    JobEmbedding,
    JobMatch,
    MatchStatus,
    Profile,
    ProfileEmbedding,
)
from sanket.profiles.store import profiles_needing_embedding
from sanket.queue.tasks import (
    NO_EMBEDDING,
    TASK_EMBED_PROFILE,
    TASK_MATCH_JOB,
    TASK_MATCH_PROFILE,
    embed_profile_key,
    match_job_key,
    match_profile_key,
)


@dataclass(frozen=True)
class WorkItem:
    task_name: str
    payload: dict[str, Any]
    key: str


def _embed_item(profile_id: int, content_hash: str) -> WorkItem:
    return WorkItem(
        TASK_EMBED_PROFILE,
        {"profile_id": profile_id, "content_hash": content_hash},
        embed_profile_key(profile_id, content_hash),
    )


def _job_item(job_id: int, embedding_hash: str) -> WorkItem:
    return WorkItem(
        TASK_MATCH_JOB,
        {"job_id": job_id, "embedding_hash": embedding_hash},
        match_job_key(job_id, embedding_hash),
    )


def _profile_item(profile_id: int, content_hash: str, embedding_hash: str) -> WorkItem:
    return WorkItem(
        TASK_MATCH_PROFILE,
        {
            "profile_id": profile_id,
            "content_hash": content_hash,
            "embedding_hash": embedding_hash,
        },
        match_profile_key(profile_id, content_hash, embedding_hash),
    )


def embed_work(conn: Connection, spec: EmbeddingSpec, limit: int) -> list[WorkItem]:
    """`embed_profile` for every profile that is pending or failed, or has no vector for the
    configured model version, oldest first."""
    return [_embed_item(pid, chash) for pid, chash in profiles_needing_embedding(conn, spec, limit)]


def _alive_embedding(spec: EmbeddingSpec) -> Any:
    return (
        select(JobEmbedding.job_id.label("job_id"), JobEmbedding.content_hash.label("hash"))
        .join(Job, Job.id == JobEmbedding.job_id)
        .where(
            JobEmbedding.model_name == spec.model_name,
            JobEmbedding.model_version == spec.model_version,
            Job.posting_count > 0,
        )
    )


def job_exists(conn: Connection, job_id: int) -> bool:
    return conn.execute(select(Job.id).where(Job.id == job_id)).first() is not None


def job_work(
    conn: Connection,
    spec: EmbeddingSpec,
    *,
    job_id: int | None = None,
    since: datetime | None = None,
) -> list[WorkItem]:
    """`match_job` for live jobs with an embedding (those whose embedding changed since
    `since`, if given), and a withdrawing `match_job` for every job that still holds an active
    match but has died or lost its embedding. With `job_id`, just that job, one way or the
    other."""
    alive = _alive_embedding(spec)
    if job_id is not None:
        alive = alive.where(JobEmbedding.job_id == job_id)
    if since is not None:
        alive = alive.where(JobEmbedding.updated_at >= since)
    items = [_job_item(row.job_id, row.hash) for row in conn.execute(alive.order_by("job_id"))]
    if since is None or job_id is not None:
        items += _withdrawing_items(conn, spec, job_id, {item.payload["job_id"] for item in items})
    return sorted(items, key=lambda item: item.payload["job_id"])


def _withdrawing_items(
    conn: Connection, spec: EmbeddingSpec, job_id: int | None, already: set[int]
) -> list[WorkItem]:
    alive = _alive_embedding(spec).where(JobEmbedding.job_id == JobMatch.job_id).exists()
    stmt = (
        select(JobMatch.job_id)
        .where(JobMatch.status == MatchStatus.ACTIVE, ~alive)
        .distinct()
        .order_by(JobMatch.job_id)
    )
    if job_id is not None:
        stmt = stmt.where(JobMatch.job_id == job_id)
    ids = [jid for jid in conn.execute(stmt).scalars() if jid not in already]
    if job_id is not None and not ids and job_id not in already:
        # A job that holds no active match and has no embedding: nothing to withdraw, but the
        # caller asked for it by id, so a withdrawing task keeps the answer uniform.
        ids = [job_id]
    return [_job_item(jid, NO_EMBEDDING) for jid in ids]


def profile_work(
    conn: Connection,
    spec: EmbeddingSpec,
    *,
    profile_id: int | None = None,
    since: datetime | None = None,
) -> list[WorkItem]:
    """`match_profile` for every profile that is embedded for `spec` and for every switched-off
    profile (whose matches must be withdrawn), optionally only those changed since `since`."""
    embedding_hash = (
        select(ProfileEmbedding.content_hash)
        .where(
            ProfileEmbedding.profile_id == Profile.id,
            ProfileEmbedding.model_name == spec.model_name,
            ProfileEmbedding.model_version == spec.model_version,
        )
        .scalar_subquery()
    )
    embedded = exists().where(
        ProfileEmbedding.profile_id == Profile.id,
        ProfileEmbedding.model_name == spec.model_name,
        ProfileEmbedding.model_version == spec.model_version,
    )
    stmt = (
        select(Profile.id, Profile.content_hash, embedding_hash.label("embedding_hash"))
        .where(((Profile.embedding_status == EmbeddingStatus.READY) & embedded) | ~Profile.active)
        .order_by(Profile.id)
    )
    if profile_id is not None:
        stmt = stmt.where(Profile.id == profile_id)
    if since is not None:
        stmt = stmt.where(Profile.updated_at >= since)
    return [
        _profile_item(row.id, row.content_hash, row.embedding_hash or NO_EMBEDDING)
        for row in conn.execute(stmt)
    ]


def describe(items: Sequence[WorkItem], limit: int = 10) -> str:
    """A short list of what the items are, for a log line."""
    shown = [f"{item.task_name}:{item.key}" for item in items[:limit]]
    more = len(items) - len(shown)
    return ", ".join(shown) + (f" ... and {more} more" if more > 0 else "")
