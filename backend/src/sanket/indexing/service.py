"""Keep the full-text vector and the embedding of every canonical job current.

`index_pending` scans jobs in id order (keyset pagination, one page per database read),
works out what each job needs and handles the first `limit` jobs that need something.
`index_jobs` does the same for given ids, for a caller that knows which jobs it touched.

For each job, from its search document (`sanket.indexing.document`):

- A job with no postings is dead: its search vector and all its embeddings are removed, so
  search never returns it. Its row stays, ids are stable (see canonicalisation).
- The tsvector is rewritten only when `job.search_hash` differs from the hash of the
  current document.
- The embedding is requested only when no `job_embedding` row exists for the active
  (model_name, model_version) or its `content_hash` differs from the current hash. A second
  run on unchanged data makes no embedding call.

Failures are isolated. A failed embedding batch is logged and its jobs counted as failed;
they stay pending for the next run (nothing is stored, nothing retried in a loop). A batch
the provider rejects as invalid is retried text by text to find the offender. After
`MAX_CONSECUTIVE_FAILED_BATCHES` batches in a row fail completely (quota, outage, bad key)
the run stops. Embeddings are written per batch, so an interrupted run loses nothing.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient, EmbeddingError, check_vectors, spec_of
from sanket.extraction.schema import JobExtraction
from sanket.indexing.config import IndexConfig, check_dimensions
from sanket.indexing.document import (
    JobFields,
    PostingFields,
    build_embedding_text,
    build_search_document,
    build_weighted_text,
    embedding_hash,
    search_hash,
)
from sanket.indexing.store import (
    EmbeddingWrite,
    JobSource,
    SearchWrite,
    load_job_sources,
    remove_index_entries,
    write_embeddings,
    write_search_vectors,
)

MAX_CONSECUTIVE_FAILED_BATCHES = 3

logger = logging.getLogger(__name__)


class Action(StrEnum):
    INDEX = "index"
    REMOVE = "remove"
    SKIP_NO_TEXT = "skip_no_text"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class JobPlan:
    """What to do for one job."""

    job_id: int
    action: Action
    # Set only for the parts that need writing.
    search_write: SearchWrite | None = None
    embedding_text: str | None = None
    embedding_hash: str | None = None


@dataclass(frozen=True)
class IndexSummary:
    scanned: int = 0
    tsvector_updated: int = 0
    embedded: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped_no_text: int = 0
    failed: int = 0
    applied: bool = False
    stopped_early: bool = False

    def line(self, model: str = "") -> str:
        mode = "apply" if self.applied else "dry-run"
        return (
            f"indexing mode={mode} model={model} scanned={self.scanned} "
            f"tsvector_updated={self.tsvector_updated} embedded={self.embedded} "
            f"unchanged={self.unchanged} removed={self.removed} "
            f"skipped_no_text={self.skipped_no_text} failed={self.failed} "
            f"stopped_early={str(self.stopped_early).lower()}"
        )


@dataclass
class _Run:
    """Totals of one run. Internal to this module."""

    apply: bool
    remaining: int | None
    scanned: int = 0
    tsvector_updated: int = 0
    embedded: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped_no_text: int = 0
    failed_ids: set[int] = field(default_factory=set)
    failed_batches_in_a_row: int = 0
    stopped: bool = False
    stopped_early: bool = False

    def summary(self) -> IndexSummary:
        return IndexSummary(
            scanned=self.scanned,
            tsvector_updated=self.tsvector_updated,
            embedded=self.embedded,
            unchanged=self.unchanged,
            removed=self.removed,
            skipped_no_text=self.skipped_no_text,
            failed=len(self.failed_ids),
            applied=self.apply,
            stopped_early=self.stopped_early,
        )


def parse_extraction(data: dict[str, Any] | None, job_id: int) -> JobExtraction | None:
    """The stored extraction as a model, or None if there is none or it no longer validates."""
    if data is None:
        return None
    try:
        return JobExtraction.model_validate(data)
    except ValidationError:
        logger.warning("Job %d: stored extraction does not validate, indexing without it", job_id)
        return None


def plan_job(source: JobSource, cfg: IndexConfig) -> JobPlan:
    """Decide what one job needs, from what is stored and what the document now says."""
    if source.posting_count == 0:
        dead_entries = source.has_search_vector or source.has_any_embedding
        action = Action.REMOVE if dead_entries or source.search_hash else Action.UNCHANGED
        return JobPlan(source.job_id, action)
    doc = build_search_document(
        JobFields(source.title, source.company, source.location),
        parse_extraction(source.extraction, source.job_id),
        PostingFields(source.description),
        cfg.max_description_chars,
    )
    if doc.is_empty:
        return JobPlan(source.job_id, Action.SKIP_NO_TEXT)
    text = build_embedding_text(doc)
    new_search_hash = search_hash(doc)
    new_embedding_hash = embedding_hash(
        text, cfg.spec.model_name, cfg.spec.model_version, cfg.spec.dimensions
    )
    needs_tsvector = source.search_hash != new_search_hash or not source.has_search_vector
    needs_embedding = source.embedding_hash != new_embedding_hash
    if not (needs_tsvector or needs_embedding):
        return JobPlan(source.job_id, Action.UNCHANGED)
    return JobPlan(
        job_id=source.job_id,
        action=Action.INDEX,
        search_write=(
            SearchWrite(source.job_id, build_weighted_text(doc), new_search_hash)
            if needs_tsvector
            else None
        ),
        embedding_text=text if needs_embedding else None,
        embedding_hash=new_embedding_hash if needs_embedding else None,
    )


def _classify(run: _Run, sources: Sequence[JobSource], cfg: IndexConfig) -> list[JobPlan]:
    """Plan jobs in order until the run's work limit is used up; count what needs nothing."""
    work: list[JobPlan] = []
    for source in sources:
        plan = plan_job(source, cfg)
        run.scanned += 1
        if plan.action is Action.UNCHANGED:
            run.unchanged += 1
        elif plan.action is Action.SKIP_NO_TEXT:
            run.skipped_no_text += 1
        else:
            work.append(plan)
            if run.remaining is not None:
                run.remaining -= 1
                if run.remaining <= 0:
                    run.stopped = True
                    break
    return work


def _remove(run: _Run, plans: Sequence[JobPlan], db_engine: Engine) -> None:
    ids = [plan.job_id for plan in plans if plan.action is Action.REMOVE]
    if not ids:
        return
    if not run.apply:
        run.removed += len(ids)
        return
    try:
        with db_engine.begin() as conn:
            remove_index_entries(conn, ids)
    except SQLAlchemyError:
        logger.exception("Removing the index entries of %d dead jobs failed", len(ids))
        run.failed_ids.update(ids)
        return
    run.removed += len(ids)


def _update_tsvectors(run: _Run, plans: Sequence[JobPlan], db_engine: Engine) -> None:
    writes = [plan.search_write for plan in plans if plan.search_write is not None]
    if not writes:
        return
    if not run.apply:
        run.tsvector_updated += len(writes)
        return
    try:
        with db_engine.begin() as conn:
            write_search_vectors(conn, writes)
    except SQLAlchemyError:
        logger.exception("Updating %d search vectors failed", len(writes))
        run.failed_ids.update(write.job_id for write in writes)
        return
    run.tsvector_updated += len(writes)


def _embed_texts(
    client: EmbeddingClient, plans: Sequence[JobPlan], cfg: IndexConfig
) -> tuple[list[EmbeddingWrite], list[JobPlan]]:
    """Embed these plans: the successful writes, and the plans that failed.

    When the provider rejects the input itself, the texts are retried one by one so one bad
    job does not take its whole batch down with it.
    """
    texts = [plan.embedding_text or "" for plan in plans]
    try:
        vectors = check_vectors(client.embed_documents(texts), len(plans), cfg.spec.dimensions)
    except EmbeddingError as error:
        logger.warning("Embedding %d jobs failed: %s", len(plans), error)
        if error.retryable or len(plans) == 1:
            return [], list(plans)
    else:
        writes = [
            EmbeddingWrite(plan.job_id, plan.embedding_hash or "", vector)
            for plan, vector in zip(plans, vectors, strict=True)
        ]
        return writes, []
    writes, failed = [], []
    for plan in plans:
        one_write, one_failed = _embed_texts(client, [plan], cfg)
        writes += one_write
        failed += one_failed
    return writes, failed


def _store_embeddings(
    run: _Run, writes: Sequence[EmbeddingWrite], cfg: IndexConfig, db_engine: Engine
) -> None:
    try:
        with db_engine.begin() as conn:
            write_embeddings(conn, cfg.spec, writes)
    except SQLAlchemyError:
        logger.exception("Storing %d embeddings failed", len(writes))
        run.failed_ids.update(write.job_id for write in writes)
        return
    run.embedded += len(writes)


def _embed_batch(
    run: _Run,
    client: EmbeddingClient,
    plans: Sequence[JobPlan],
    cfg: IndexConfig,
    db_engine: Engine,
) -> None:
    writes, failed = _embed_texts(client, plans, cfg)
    run.failed_ids.update(plan.job_id for plan in failed)
    if writes:
        run.failed_batches_in_a_row = 0
        _store_embeddings(run, writes, cfg, db_engine)
        return
    run.failed_batches_in_a_row += 1
    if run.failed_batches_in_a_row >= MAX_CONSECUTIVE_FAILED_BATCHES:
        logger.error("Stopping: %d embedding batches in a row failed", run.failed_batches_in_a_row)
        run.stopped = True
        run.stopped_early = True


def _embed(
    run: _Run,
    client: EmbeddingClient | None,
    plans: Sequence[JobPlan],
    cfg: IndexConfig,
    db_engine: Engine,
) -> None:
    todo = [plan for plan in plans if plan.embedding_text is not None]
    if not run.apply:
        run.embedded += len(todo)
        return
    if client is None:
        raise ValueError("an embedding client is required to apply")
    size = cfg.embedding_batch_size
    for start in range(0, len(todo), size):
        _embed_batch(run, client, todo[start : start + size], cfg, db_engine)
        if run.stopped_early:
            return


def _handle_page(
    run: _Run,
    client: EmbeddingClient | None,
    sources: Sequence[JobSource],
    cfg: IndexConfig,
    db_engine: Engine,
) -> None:
    plans = _classify(run, sources, cfg)
    _remove(run, plans, db_engine)
    _update_tsvectors(run, plans, db_engine)
    _embed(run, client, plans, cfg, db_engine)


def _prepare(
    cfg: IndexConfig, client: EmbeddingClient | None, apply: bool, db_engine: Engine
) -> None:
    check_dimensions(cfg.spec.dimensions, db_engine)
    if apply and client is None:
        raise ValueError("an embedding client is required to apply")
    if client is not None and spec_of(client) != cfg.spec:
        raise ValueError(f"client {spec_of(client)} does not match the configured {cfg.spec}")


def index_pending(
    cfg: IndexConfig,
    client: EmbeddingClient | None = None,
    *,
    limit: int | None = None,
    apply: bool = False,
    db_engine: Engine = engine,
) -> IndexSummary:
    """Index the first `limit` (default `cfg.batch_limit`) jobs that need work.

    Without `apply` nothing is written and the client is never called; the summary counts
    what an apply run would do.
    """
    _prepare(cfg, client, apply, db_engine)
    run = _Run(apply=apply, remaining=limit if limit is not None else cfg.batch_limit)
    last_id = 0
    while not run.stopped:
        with db_engine.connect() as conn:
            sources = load_job_sources(
                conn,
                cfg.spec,
                cfg.max_description_chars,
                after_id=last_id,
                limit=cfg.scan_page_size,
            )
        if not sources:
            break
        _handle_page(run, client, sources, cfg, db_engine)
        last_id = sources[-1].job_id
    return run.summary()


def index_jobs(
    job_ids: Sequence[int],
    cfg: IndexConfig,
    client: EmbeddingClient,
    db_engine: Engine = engine,
) -> IndexSummary:
    """Index just these jobs and write the result, for callers that know what they touched.

    Ids that do not exist are ignored. There is no work limit: the caller chose the jobs.
    """
    _prepare(cfg, client, True, db_engine)
    run = _Run(apply=True, remaining=None)
    ids = sorted(set(job_ids))
    for start in range(0, len(ids), cfg.scan_page_size):
        if run.stopped:
            break
        with db_engine.connect() as conn:
            sources = load_job_sources(
                conn,
                cfg.spec,
                cfg.max_description_chars,
                job_ids=ids[start : start + cfg.scan_page_size],
            )
        _handle_page(run, client, sources, cfg, db_engine)
    return run.summary()
