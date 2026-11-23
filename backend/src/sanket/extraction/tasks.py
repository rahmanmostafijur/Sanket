"""Extraction on the task queue: one `extract_posting` task per pending posting.

The key is the posting id plus its content hash, so a posting is queued once per content: an
unchanged posting is never pending (the hash gate in `is_pending`) and never reaches the model,
and a changed one gets a new key. The handler re-checks that the posting is still pending, so a
stale or duplicate task is a cheap no-op. A provider error raises, so the queue retries with
backoff instead of using up the posting's attempts.

`python -m sanket.extraction.tasks [--limit N]` queues the pending postings (ingest does the same
after each run when REDIS_URL is set).
"""

import argparse
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select

from sanket.config import Settings, settings
from sanket.db import engine
from sanket.extraction.llm import GeminiClient, LlmClient
from sanket.extraction.runner import (
    ExtractionConfig,
    Outcome,
    config_from_settings,
    extract_posting,
    is_pending,
)
from sanket.models import Posting
from sanket.observability.logs import configure_logging
from sanket.queue.base import TaskContext, TaskQueue, TaskRegistry
from sanket.queue.connection import task_queue_from_settings

TASK_EXTRACT_POSTING = "extract_posting"

logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """The model provider failed; raised so the queue retries the task later."""


class ExtractPostingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posting_id: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=100)


def extract_posting_key(posting_id: int, content_hash: str) -> str:
    return f"{TASK_EXTRACT_POSTING}:{posting_id}:{content_hash}"


def gemini_client_from_settings(config: Settings) -> GeminiClient | None:
    if config.gemini_api_key is None:
        return None
    return GeminiClient(
        config.gemini_api_key,
        config.gemini_model,
        requests_per_minute=config.gemini_requests_per_minute,
    )


def register_extraction(
    registry: TaskRegistry,
    client: LlmClient | None,
    cfg: ExtractionConfig,
    db_engine: Engine = engine,
) -> None:
    """Add the `extract_posting` handler. Without a client the task fails into the retries
    and then the dead-letter store, as a misconfiguration should."""

    def handler(payload: Mapping[str, Any], context: TaskContext) -> None:
        task = ExtractPostingPayload.model_validate(payload)
        if client is None:
            raise ProviderUnavailableError("GEMINI_API_KEY is not set")
        outcome = extract_posting(task.posting_id, client, cfg, db_engine)
        if outcome is Outcome.PROVIDER_ERROR:
            raise ProviderUnavailableError(f"provider error on posting {task.posting_id}")
        logger.info("Extraction of posting %d: %s", task.posting_id, outcome.value)

    registry.register(TASK_EXTRACT_POSTING, handler)


def enqueue_pending(
    queue: TaskQueue, cfg: ExtractionConfig, limit: int, db_engine: Engine = engine
) -> int:
    """Queue up to `limit` pending postings, newest first; returns how many were offered."""
    stmt = (
        select(Posting.id, Posting.content_hash)
        .where(is_pending(cfg))
        .order_by(Posting.id.desc())
        .limit(limit)
    )
    with db_engine.connect() as conn:
        rows = conn.execute(stmt).all()
    for posting_id, content_hash in rows:
        queue.enqueue(
            TASK_EXTRACT_POSTING,
            {"posting_id": posting_id, "content_hash": content_hash},
            key=extract_posting_key(posting_id, content_hash),
        )
    return len(rows)


def enqueue_after_ingest(config: Settings = settings, db_engine: Engine = engine) -> None:
    """Queue extraction for new and changed postings; a no-op without REDIS_URL."""
    queue = task_queue_from_settings(config)
    if queue is None:
        logger.info("REDIS_URL is not set: extraction is not queued after ingest")
        return
    try:
        count = enqueue_pending(
            queue, config_from_settings(config), config.extraction_batch_limit, db_engine
        )
    except Exception:  # queueing must never fail the ingest run that already stored postings
        logger.exception("Queueing extraction after ingest failed")
        return
    logger.info("extraction queued postings=%d", count)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Queue pending postings for extraction.")
    parser.add_argument("--limit", type=int, default=settings.extraction_batch_limit)
    args = parser.parse_args()
    queue = task_queue_from_settings(settings)
    if queue is None:
        raise SystemExit("REDIS_URL is not set: the extraction queue needs Redis")
    count = enqueue_pending(queue, config_from_settings(settings), args.limit)
    logger.info("extraction queued postings=%d", count)


if __name__ == "__main__":
    main()
