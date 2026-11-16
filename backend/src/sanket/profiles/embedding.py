"""Embed profiles, behind a hash gate like the jobs'.

`embed_profile` reads the profile, hashes its embedding text with the model, version and
dimension (`profile_embedding_hash`) and calls the provider only when no stored embedding has
that hash. The vector is stored and the profile marked `ready`, but only if the profile still
has the content that was embedded: a save that landed meanwhile keeps it `pending` and its own
task embeds the new text.

A provider failure is recorded on the profile and raised, so the queue retries it with
backoff. The status is `failed` when the failure is final (the last attempt, or an input the
provider rejected), `pending` while retries remain, and it becomes `ready` as soon as an
attempt succeeds.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient, EmbeddingError, EmbeddingSpec, check_vectors
from sanket.models import EmbeddingStatus
from sanket.profiles.store import (
    load_profile,
    mark_embedding,
    stored_embedding_hash,
    write_embedding,
)
from sanket.profiles.text import profile_embedding_hash

logger = logging.getLogger(__name__)


class EmbedOutcome(StrEnum):
    EMBEDDED = "embedded"
    # The stored embedding already matches the profile's text, model and version.
    UNCHANGED = "unchanged"
    # The profile was deleted before it could be embedded.
    MISSING = "missing"


@dataclass(frozen=True)
class EmbedResult:
    outcome: EmbedOutcome
    # The profile's content hash and the embedding hash that are now stored; None if missing.
    profile_hash: str | None = None
    embedding_hash: str | None = None


@dataclass(frozen=True)
class EmbedSummary:
    embedded: int = 0
    unchanged: int = 0
    missing: int = 0
    failed: int = 0


def _record_failure(
    profile_id: int, profile_hash: str, error: EmbeddingError, final: bool, db_engine: Engine
) -> None:
    status = EmbeddingStatus.FAILED if final or not error.retryable else EmbeddingStatus.PENDING
    with db_engine.begin() as conn:
        mark_embedding(conn, profile_id, profile_hash, status, str(error))


def embed_profile(
    profile_id: int,
    client: EmbeddingClient,
    spec: EmbeddingSpec,
    *,
    final_attempt: bool = True,
    db_engine: Engine = engine,
) -> EmbedResult:
    """Embed one profile if its stored embedding is missing or stale. Raises EmbeddingError."""
    with db_engine.connect() as conn:
        profile = load_profile(conn, profile_id)
        stored = stored_embedding_hash(conn, profile_id, spec) if profile else None
    if profile is None:
        return EmbedResult(EmbedOutcome.MISSING)
    wanted = profile_embedding_hash(
        profile.search_text, spec.model_name, spec.model_version, spec.dimensions
    )
    if stored == wanted:
        with db_engine.begin() as conn:
            mark_embedding(conn, profile_id, profile.content_hash, EmbeddingStatus.READY)
        return EmbedResult(EmbedOutcome.UNCHANGED, profile.content_hash, wanted)
    try:
        [vector] = check_vectors([client.embed_query(profile.search_text)], 1, spec.dimensions)
    except EmbeddingError as error:
        logger.warning("Embedding profile %d failed: %s", profile_id, error)
        _record_failure(profile_id, profile.content_hash, error, final_attempt, db_engine)
        raise
    try:
        with db_engine.begin() as conn:
            write_embedding(conn, profile_id, spec, wanted, vector)
            mark_embedding(conn, profile_id, profile.content_hash, EmbeddingStatus.READY)
    except IntegrityError:
        # Only the foreign key can fail here: the profile was deleted while it was embedded.
        logger.info("Profile %d was deleted while it was being embedded", profile_id)
        return EmbedResult(EmbedOutcome.MISSING)
    return EmbedResult(EmbedOutcome.EMBEDDED, profile.content_hash, wanted)


def embed_profiles(
    profile_ids: Sequence[int],
    client: EmbeddingClient,
    spec: EmbeddingSpec,
    db_engine: Engine = engine,
) -> EmbedSummary:
    """Embed each profile on its own; a failure is counted and does not stop the others."""
    counts = {"embedded": 0, "unchanged": 0, "missing": 0, "failed": 0}
    for profile_id in profile_ids:
        try:
            result = embed_profile(profile_id, client, spec, db_engine=db_engine)
        except EmbeddingError:
            counts["failed"] += 1
        else:
            counts[result.outcome.value] += 1
    return EmbedSummary(**counts)
