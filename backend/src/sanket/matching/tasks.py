"""The queue tasks of the matching pipeline (ADR 0005, ADR 0006).

- `embed_profile`: embed a saved profile (behind the hash gate in `sanket.profiles.embedding`)
  and, once its embedding is stored, queue `match_profile`. A retryable provider error
  propagates so the queue retries it with backoff (the profile stays `pending`, and is marked
  `failed` on the last attempt); an error that repeating cannot fix is a permanent failure.
  A profile deleted in the meantime is a no-op.
- `match_job`: match one job against the stored profiles, or withdraw its matches when it has
  died or has no embedding (the indexing trigger queues it with `NO_EMBEDDING` as the hash in
  the second case; the handler looks at the database, never at the hash in the payload).
- `match_profile`: match one profile against recent jobs.

The payloads are validated here; one that is not valid cannot succeed on a retry and is a
permanent failure. All three handlers are idempotent: delivery is at least once.
`build_registry` takes every dependency as an argument so tests (and other phases) can
inject fakes; `registry_from_settings` builds the production set.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine

from sanket.config import Settings, settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient, EmbeddingError, spec_of
from sanket.embeddings.gemini import GeminiEmbeddingClient
from sanket.matching.config import MatchConfig, config_from_settings
from sanket.matching.notify import MatchNotifier, NoopNotifier
from sanket.matching.service import match_job, match_profile
from sanket.profiles.embedding import EmbedOutcome, embed_profile
from sanket.queue.base import Handler, PermanentTaskError, TaskContext, TaskQueue, TaskRegistry
from sanket.queue.tasks import (
    TASK_EMBED_PROFILE,
    TASK_MATCH_JOB,
    TASK_MATCH_PROFILE,
    EmbedProfilePayload,
    MatchJobPayload,
    MatchProfilePayload,
    match_profile_key,
)

logger = logging.getLogger(__name__)

MAX_REPORTED_ERRORS = 3

PayloadT = TypeVar("PayloadT", bound=BaseModel)


@dataclass(frozen=True)
class MatchTaskDeps:
    """What the handlers need. `embedder` is None when no embedding key is configured and
    `queue` is None when there is no queue to chain the next task on."""

    cfg: MatchConfig
    embedder: EmbeddingClient | None = None
    queue: TaskQueue | None = None
    notifier: MatchNotifier = field(default_factory=NoopNotifier)
    db_engine: Engine = engine


def _validated(model: type[PayloadT], payload: Mapping[str, Any]) -> PayloadT:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        problems = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)[:MAX_REPORTED_ERRORS]
        ]
        raise PermanentTaskError(f"invalid {model.__name__}: {'; '.join(problems)}") from error


def _embed(deps: MatchTaskDeps, payload: EmbedProfilePayload, context: TaskContext) -> None:
    if deps.embedder is None:
        raise PermanentTaskError("cannot embed a profile: GEMINI_API_KEY is not set")
    try:
        result = embed_profile(
            payload.profile_id,
            deps.embedder,
            spec_of(deps.embedder),
            final_attempt=context.is_final_attempt,
            db_engine=deps.db_engine,
        )
    except EmbeddingError as error:
        if error.retryable:
            raise
        raise PermanentTaskError(
            f"the provider rejected profile {payload.profile_id}: {error}"
        ) from error
    if result.outcome is EmbedOutcome.MISSING:
        logger.info("Profile %d no longer exists; nothing to embed", payload.profile_id)
        return
    if deps.queue is None or result.profile_hash is None or result.embedding_hash is None:
        logger.warning("No task queue: profile %d is embedded but not matched", payload.profile_id)
        return
    deps.queue.enqueue(
        TASK_MATCH_PROFILE,
        {
            "profile_id": payload.profile_id,
            "content_hash": result.profile_hash,
            "embedding_hash": result.embedding_hash,
        },
        key=match_profile_key(payload.profile_id, result.profile_hash, result.embedding_hash),
    )


def _match_job(deps: MatchTaskDeps, payload: MatchJobPayload) -> None:
    summary = match_job(payload.job_id, deps.cfg, notifier=deps.notifier, db_engine=deps.db_engine)
    logger.info("Matched job %d: %s", payload.job_id, summary)


def _match_profile(deps: MatchTaskDeps, payload: MatchProfilePayload) -> None:
    summary = match_profile(
        payload.profile_id, deps.cfg, notifier=deps.notifier, db_engine=deps.db_engine
    )
    logger.info("Matched profile %d: %s", payload.profile_id, summary)


def build_registry(deps: MatchTaskDeps) -> TaskRegistry:
    """The handlers of the three tasks, bound to `deps`."""

    def embed_handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        _embed(deps, _validated(EmbedProfilePayload, payload), context)

    def match_job_handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        _match_job(deps, _validated(MatchJobPayload, payload))

    def match_profile_handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        _match_profile(deps, _validated(MatchProfilePayload, payload))

    handlers: dict[str, Handler] = {
        TASK_EMBED_PROFILE: embed_handler,
        TASK_MATCH_JOB: match_job_handler,
        TASK_MATCH_PROFILE: match_profile_handler,
    }
    registry = TaskRegistry()
    for name, handler in handlers.items():
        registry.register(name, handler)
    return registry


def gemini_client_from_settings(config: Settings) -> GeminiEmbeddingClient | None:
    """The embedding client for the configured model, or None without GEMINI_API_KEY."""
    if config.gemini_api_key is None:
        return None
    return GeminiEmbeddingClient(
        config.gemini_api_key,
        config.embedding_model,
        config.embedding_dimensions,
        model_version=config.embedding_model_version,
        requests_per_minute=config.embedding_requests_per_minute,
    )


def registry_from_settings(
    config: Settings = settings,
    *,
    queue: TaskQueue | None = None,
    embedder: EmbeddingClient | None = None,
    notifier: MatchNotifier | None = None,
    db_engine: Engine = engine,
) -> TaskRegistry:
    """The production registry; every dependency can be replaced for tests."""
    return build_registry(
        MatchTaskDeps(
            cfg=config_from_settings(config),
            embedder=embedder if embedder is not None else gemini_client_from_settings(config),
            queue=queue,
            notifier=notifier if notifier is not None else NoopNotifier(),
            db_engine=db_engine,
        )
    )
