"""Evaluate search quality against labelled queries: `python -m sanket.search.evaluate`.

Runs the same retrieval the API uses (`sanket.search.retrieval.retrieve`, called directly, no
HTTP) for every labelled query against the database in DATABASE_URL, with the embedding
client the settings configure (the real Gemini client when GEMINI_API_KEY is set, so vector
and hybrid runs make one real embedding call per distinct query). Prints a per-query table and
the means, and can compare hybrid, text-only and vector-only side by side. It measures; it
tunes nothing. See docs/search-evaluation.md for the file format and how to read the output.
"""

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from sanket.config import settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient
from sanket.indexing.config import check_dimensions
from sanket.indexing.filters import SearchFilters
from sanket.indexing.queries import fulltext_candidates
from sanket.models import Job
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.client import query_embedding_client
from sanket.search.labels import LabelError, LabelledQuery, load_labels
from sanket.search.metrics import Aggregate, QueryMetrics, aggregate, score_query
from sanket.search.report import format_report, report_to_dict
from sanket.search.retrieval import SearchConfig, SearchMode, retrieve, search_config_from_settings

DEFAULT_K = 10
FIND_LIMIT = 15
ALL_MODES = (SearchMode.HYBRID, SearchMode.TEXT, SearchMode.VECTOR)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryResult:
    query: str
    # Fingerprints of the top k results, best first.
    ranked: tuple[str, ...]
    metrics: QueryMetrics
    # The embedding was unavailable, so a vector or hybrid result is text-only.
    degraded: bool
    # Labelled jobs that are not in the database at all (they can never be retrieved).
    missing_refs: tuple[str, ...]


@dataclass(frozen=True)
class ModeReport:
    mode: SearchMode
    results: tuple[QueryResult, ...]
    summary: Aggregate


@dataclass(frozen=True)
class EvalReport:
    k: int
    candidates: int
    modes: tuple[ModeReport, ...]


def fingerprints_by_job_id(job_ids: Sequence[int], db_engine: Engine) -> dict[int, str]:
    if not job_ids:
        return {}
    stmt = select(Job.id, Job.fingerprint).where(Job.id.in_(list(job_ids)))
    with db_engine.connect() as conn:
        return {row[0]: row[1] for row in conn.execute(stmt)}


def known_fingerprints(refs: Sequence[str], db_engine: Engine) -> set[str]:
    """Which of the given fingerprints exist as jobs in the database."""
    if not refs:
        return set()
    with db_engine.connect() as conn:
        return set(conn.scalars(select(Job.fingerprint).where(Job.fingerprint.in_(list(refs)))))


def _evaluate_query(
    labelled: LabelledQuery,
    mode: SearchMode,
    k: int,
    cfg: SearchConfig,
    client: EmbeddingClient | None,
    cache: QueryEmbeddingCache,
    known: set[str],
    db_engine: Engine,
) -> QueryResult:
    retrieval = retrieve(
        labelled.query, SearchFilters(), cfg, client, mode=mode, cache=cache, db_engine=db_engine
    )
    top_ids = [item.job_id for item in retrieval.items[:k]]
    by_id = fingerprints_by_job_id(top_ids, db_engine)
    ranked = tuple(by_id[job_id] for job_id in top_ids if job_id in by_id)
    grades = labelled.grades
    return QueryResult(
        query=labelled.query,
        ranked=ranked,
        metrics=score_query(ranked, grades, k),
        degraded=retrieval.degraded and mode is not SearchMode.TEXT,
        missing_refs=tuple(ref for ref in grades if ref not in known),
    )


def run_evaluation(
    labels: Sequence[LabelledQuery],
    k: int,
    modes: Sequence[SearchMode],
    cfg: SearchConfig,
    client: EmbeddingClient | None,
    db_engine: Engine = engine,
) -> EvalReport:
    """Retrieve for every query in every mode and score the top k against the labels.

    Query embeddings are cached, so a query is embedded once however many modes use it.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if k > cfg.candidates:
        raise ValueError(f"k ({k}) is larger than SEARCH_CANDIDATES ({cfg.candidates})")
    cache = QueryEmbeddingCache(max(len(labels), 1))
    known = known_fingerprints([ref for item in labels for ref in item.grades], db_engine)
    reports = []
    for mode in modes:
        results = tuple(
            _evaluate_query(item, mode, k, cfg, client, cache, known, db_engine) for item in labels
        )
        reports.append(ModeReport(mode, results, aggregate([r.metrics for r in results])))
    return EvalReport(k=k, candidates=cfg.candidates, modes=tuple(reports))


@dataclass(frozen=True)
class JobRef:
    fingerprint: str
    title: str
    company: str
    location: str | None


def find_job_refs(query: str, db_engine: Engine, limit: int = FIND_LIMIT) -> list[JobRef]:
    """Full-text search for jobs, to copy their fingerprints into a labelled file."""
    found = fulltext_candidates(query, limit, db_engine, filters=SearchFilters())
    stmt = select(Job.id, Job.fingerprint, Job.title, Job.company, Job.location).where(
        Job.id.in_([candidate.job_id for candidate in found])
    )
    with db_engine.connect() as conn:
        rows = {row[0]: JobRef(*row[1:]) for row in conn.execute(stmt)}
    return [rows[candidate.job_id] for candidate in found if candidate.job_id in rows]


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--queries", type=Path, help="labelled queries (JSONL)")
    parser.add_argument("--k", type=_positive_int, default=DEFAULT_K, help="cut-off (default 10)")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ALL_MODES] + ["all"],
        default=SearchMode.HYBRID.value,
        help="retrieval to evaluate; 'all' compares the three side by side",
    )
    parser.add_argument("--json", type=Path, dest="json_path", help="also write the report here")
    parser.add_argument(
        "--find", metavar="TEXT", help="list jobs matching TEXT with their fingerprints, then exit"
    )
    return parser.parse_args(argv)


def _modes(choice: str) -> tuple[SearchMode, ...]:
    return ALL_MODES if choice == "all" else (SearchMode(choice),)


def _database_label(db_engine: Engine) -> str:
    url = db_engine.url
    return f"{url.host}:{url.port}/{url.database}"


def _print_found(refs: Sequence[JobRef]) -> None:
    for ref in refs:
        place = f" ({ref.location})" if ref.location else ""
        print(f"{ref.fingerprint}  {ref.title} at {ref.company}{place}")
    if not refs:
        print("no jobs match")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    if args.find:
        _print_found(find_job_refs(args.find, engine))
        return 0
    if args.queries is None:
        raise SystemExit("--queries is required (or use --find TEXT)")
    try:
        labels = load_labels(args.queries)
    except LabelError as error:
        raise SystemExit(str(error)) from error
    modes = _modes(args.mode)
    cfg = search_config_from_settings(settings)
    client = None
    if any(mode is not SearchMode.TEXT for mode in modes):
        check_dimensions(cfg.spec.dimensions, engine)
        client = query_embedding_client(settings)
        if client is None:
            raise SystemExit("GEMINI_API_KEY is not set: only --mode text can run")
    try:
        report = run_evaluation(labels, args.k, modes, cfg, client, engine)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(format_report(report, _database_label(engine)))
    if args.json_path:
        _write_json(args.json_path, report_to_dict(report, _database_label(engine)))
    degraded = any(result.degraded for mode in report.modes for result in mode.results)
    return 1 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
