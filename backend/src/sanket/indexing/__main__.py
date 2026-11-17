"""Index canonical jobs for search: the full-text vector and the embedding.

Run with `python -m sanket.indexing`. The default is a dry run that only counts what would
change and needs no API key; pass --apply to write. It handles at most --limit jobs that
need work (default INDEXING_BATCH_LIMIT) and is safe to repeat and interrupt: jobs whose
searchable content did not change are never embedded again.

An applied run also queues matching (docs/matching.md) for the jobs it embedded or removed,
when MATCH_ENQUEUE_AFTER_INDEXING is on and REDIS_URL is set. A queue that fails is logged and
does not change the run's result.
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import replace

from sanket.config import settings
from sanket.db import engine
from sanket.embeddings.gemini import GeminiEmbeddingClient
from sanket.indexing.config import check_dimensions, config_from_settings
from sanket.indexing.service import index_pending
from sanket.matching.triggers import index_observer_from_settings
from sanket.observability.logs import configure_logging


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="count changes only (default)")
    mode.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--limit", type=_positive_int, help="jobs needing work to handle")
    parser.add_argument("--batch-size", type=_positive_int, help="texts per embedding request")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    args = parse_args(argv)
    cfg = config_from_settings(settings)
    if args.batch_size:
        cfg = replace(cfg, embedding_batch_size=args.batch_size)
    check_dimensions(cfg.spec.dimensions, engine)
    client = None
    if args.apply:
        if settings.gemini_api_key is None:
            raise SystemExit("GEMINI_API_KEY is not set")
        client = GeminiEmbeddingClient(
            settings.gemini_api_key,
            cfg.spec.model_name,
            cfg.spec.dimensions,
            model_version=cfg.spec.model_version,
            requests_per_minute=settings.embedding_requests_per_minute,
        )
    observer = index_observer_from_settings(settings) if args.apply else None
    summary = index_pending(cfg, client, limit=args.limit, apply=args.apply, on_changes=observer)
    logger.info(summary.line(cfg.spec.model_name))
    if not args.apply:
        logger.info("dry run: nothing was written; pass --apply to write")
    if summary.failed or summary.stopped_early:
        raise SystemExit(f"{summary.failed} jobs failed; they stay pending for the next run")


if __name__ == "__main__":
    main()
