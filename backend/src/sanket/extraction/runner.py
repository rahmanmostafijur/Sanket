"""Batch extraction of pending postings.

`extract_posting` handles one posting by id and is safe to call from a queue worker: it
re-checks that the posting is still pending, so duplicate or stale jobs are cheap no-ops.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    Integer,
    Row,
    String,
    Text,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    not_,
    null,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.sql.base import ColumnCollection

from sanket.config import Settings, settings
from sanket.db import engine
from sanket.extraction.extract import ExtractionResult, extract
from sanket.extraction.llm import GeminiClient, LlmClient, LlmError
from sanket.extraction.prompt import PROMPT_VERSION, PostingInput, build_posting_text
from sanket.extraction.schema import SCHEMA_VERSION
from sanket.models import Posting, PostingExtraction
from sanket.observability.logs import configure_logging

STATUS_OK = "ok"
STATUS_FAILED = "failed"
# Stop the batch after this many provider errors in a row (quota, outage, bad key).
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    OK = "ok"
    FAILED = "failed"
    PROVIDER_ERROR = "provider_error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ExtractionConfig:
    model: str
    max_description_chars: int
    max_attempts: int
    excluded_sources: Sequence[str] = ()
    schema_version: int = SCHEMA_VERSION
    prompt_version: int = PROMPT_VERSION


def config_from_settings(config: Settings) -> ExtractionConfig:
    return ExtractionConfig(
        model=config.gemini_model,
        max_description_chars=config.extraction_max_description_chars,
        max_attempts=config.extraction_max_attempts,
        excluded_sources=tuple(config.extraction_excluded_sources),
    )


def is_pending(cfg: ExtractionConfig) -> ColumnElement[bool]:
    """A posting is pending unless its current content hash already has an ok extraction,
    or has failed `max_attempts` times, for the current schema and prompt versions."""
    finished = exists().where(
        PostingExtraction.posting_id == Posting.id,
        PostingExtraction.schema_version == cfg.schema_version,
        PostingExtraction.prompt_version == cfg.prompt_version,
        PostingExtraction.content_hash == Posting.content_hash,
        or_(
            PostingExtraction.status == STATUS_OK,
            PostingExtraction.attempts >= cfg.max_attempts,
        ),
    )
    return and_(~finished, Posting.source.not_in(list(cfg.excluded_sources)))


def find_pending(cfg: ExtractionConfig, limit: int, db_engine: Engine = engine) -> list[int]:
    """Ids of pending postings, newest first."""
    stmt = select(Posting.id).where(is_pending(cfg)).order_by(Posting.id.desc()).limit(limit)
    with db_engine.connect() as conn:
        return list(conn.scalars(stmt))


def load_pending_posting(conn: Connection, posting_id: int, cfg: ExtractionConfig) -> Row | None:
    stmt = select(
        Posting.id,
        Posting.content_hash,
        Posting.title,
        Posting.company,
        Posting.location,
        Posting.salary_text,
        Posting.description,
    ).where(Posting.id == posting_id, is_pending(cfg))
    return conn.execute(stmt).one_or_none()


def save_extraction(
    conn: Connection,
    posting_id: int,
    content_hash: str,
    cfg: ExtractionConfig,
    result: ExtractionResult,
) -> bool:
    """Upsert the result and return whether a row was written.

    Only validated data is stored; a failure stores the error. Nothing is written if the
    posting no longer has `content_hash` (it changed while the model was working), or if
    the write would replace an ok result with a failure.
    """
    # null() stores SQL NULL; a plain None would be stored as the JSON value null.
    data = (
        literal(result.data.model_dump(mode="json"), JSONB) if result.data else cast(null(), JSONB)
    )
    # One statement reads the posting and inserts, so a stale hash inserts no row at all.
    proposed = select(
        Posting.id,
        literal(cfg.schema_version, Integer),
        literal(cfg.prompt_version, Integer),
        Posting.content_hash,
        literal(cfg.model, String),
        literal(STATUS_OK if result.ok else STATUS_FAILED, String),
        data,
        literal(result.error, Text),
        literal(1, Integer),
        literal(result.input_tokens, Integer),
        literal(result.output_tokens, Integer),
    ).where(Posting.id == posting_id, Posting.content_hash == content_hash)
    stmt = insert(PostingExtraction).from_select(
        [
            "posting_id",
            "schema_version",
            "prompt_version",
            "content_hash",
            "model",
            "status",
            "data",
            "last_error",
            "attempts",
            "input_tokens",
            "output_tokens",
        ],
        proposed,
    )
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            PostingExtraction.posting_id,
            PostingExtraction.schema_version,
            PostingExtraction.prompt_version,
        ],
        set_={
            "model": excluded.model,
            "content_hash": excluded.content_hash,
            "status": excluded.status,
            "data": excluded.data,
            "last_error": excluded.last_error,
            "input_tokens": excluded.input_tokens,
            "output_tokens": excluded.output_tokens,
            "updated_at": func.now(),
            # Attempts count runs for the same content; a changed posting starts again at 1.
            "attempts": case(
                (
                    PostingExtraction.content_hash == excluded.content_hash,
                    PostingExtraction.attempts + 1,
                ),
                else_=1,
            ),
        },
        where=_may_overwrite(excluded),
    )
    # RETURNING yields a row only if one was inserted or updated; a rejected update or a
    # stale hash yields none. (Rowcount is not reliable for INSERT ... SELECT here.)
    return conn.execute(stmt.returning(PostingExtraction.id)).first() is not None


def _may_overwrite(excluded: ColumnCollection) -> ColumnElement[bool]:
    """Guard an existing row against duplicate writers (for example a batch and a worker).

    Never replace an ok result for the same hash with a failure. The stale-hash check is
    in the INSERT ... SELECT, so a proposed row always carries the posting's current hash.
    """
    return not_(
        and_(
            PostingExtraction.status == STATUS_OK,
            PostingExtraction.content_hash == excluded.content_hash,
            excluded.status == STATUS_FAILED,
        )
    )


def extract_posting(
    posting_id: int,
    client: LlmClient,
    cfg: ExtractionConfig,
    db_engine: Engine = engine,
) -> Outcome:
    """Extract one posting and store the result. Never stores unvalidated data."""
    with db_engine.connect() as conn:
        row = load_pending_posting(conn, posting_id, cfg)
    if row is None:
        return Outcome.SKIPPED

    posting = PostingInput(row.title, row.company, row.location, row.salary_text, row.description)
    text = build_posting_text(posting, cfg.max_description_chars)
    try:
        result = extract(client, text)
    except LlmError as error:
        # Nothing is stored, so an outage or quota error does not use up the posting's
        # attempts; it stays pending for the next run.
        logger.warning("Posting %d: provider error: %s", posting_id, error)
        return Outcome.PROVIDER_ERROR

    with db_engine.begin() as conn:
        written = save_extraction(conn, row.id, row.content_hash, cfg, result)
    if not written:
        # The posting changed during the call, or another worker already stored an ok
        # result. Either way this result is not the current answer; the posting stays
        # pending if it still needs extraction.
        logger.info("Posting %d: result not stored (stale or already extracted)", posting_id)
        return Outcome.SKIPPED
    return Outcome.OK if result.ok else Outcome.FAILED


def run_batch(
    client: LlmClient, cfg: ExtractionConfig, limit: int, db_engine: Engine = engine
) -> Counter[Outcome]:
    counts: Counter[Outcome] = Counter()
    consecutive_errors = 0
    for posting_id in find_pending(cfg, limit, db_engine):
        outcome = extract_posting(posting_id, client, cfg, db_engine)
        counts[outcome] += 1
        consecutive_errors = consecutive_errors + 1 if outcome is Outcome.PROVIDER_ERROR else 0
        if consecutive_errors >= MAX_CONSECUTIVE_PROVIDER_ERRORS:
            logger.error("Stopping: %d provider errors in a row", consecutive_errors)
            break
    return counts


def main() -> None:
    configure_logging()
    if settings.gemini_api_key is None:
        raise SystemExit("GEMINI_API_KEY is not set")
    cfg = config_from_settings(settings)
    client = GeminiClient(
        settings.gemini_api_key, cfg.model, requests_per_minute=settings.gemini_requests_per_minute
    )
    counts = run_batch(client, cfg, settings.extraction_batch_limit)
    logger.info(
        "extraction summary model=%s schema_version=%d prompt_version=%d %s",
        cfg.model,
        cfg.schema_version,
        cfg.prompt_version,
        " ".join(f"{outcome.value}={counts[outcome]}" for outcome in Outcome),
    )
    if counts[Outcome.PROVIDER_ERROR]:
        raise SystemExit(f"{counts[Outcome.PROVIDER_ERROR]} provider errors")


if __name__ == "__main__":
    main()
