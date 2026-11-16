"""Group postings into canonical jobs.

Run with `python -m sanket.canonicalise`. The default is a dry run that only counts what
would change; pass --apply to write. Only `posting.job_id` and the `job` table are written.
Postings are attached to the job with their fingerprint (created on first use), moved when
their title, company or location changed, and job aggregates are refreshed. Safe to run
repeatedly and to interrupt: a run with nothing new changes nothing.
"""

import argparse
import logging
from collections.abc import Sequence

from sanket.canonical.service import DEFAULT_BATCH_SIZE, canonicalise
from sanket.db import engine


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
    parser.add_argument("--batch-size", type=_positive_int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger = logging.getLogger(__name__)
    args = parse_args(argv)
    summary = canonicalise(engine, batch_size=args.batch_size, apply=args.apply)
    logger.info(summary.line())
    if not args.apply:
        logger.info("dry run: nothing was written; pass --apply to write")


if __name__ == "__main__":
    main()
