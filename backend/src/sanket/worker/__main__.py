"""Run the task queue worker: embeds saved profiles and matches jobs and profiles.

`python -m sanket.worker` works the queue until it is stopped (Ctrl+C or SIGTERM finish the
task in progress first). `--burst` works until the queue is empty and exits, for tests and
development. It needs REDIS_URL; GEMINI_API_KEY is needed for the profile embedding task.
"""

import argparse
import logging
from collections.abc import Sequence

from sanket.config import settings
from sanket.worker.run import run_worker


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--burst", action="store_true", help="exit when the queue is empty instead of waiting"
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="run tasks in the worker process (always on Windows) instead of forking per task",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    run_worker(settings, burst=args.burst, simple=args.simple)


if __name__ == "__main__":
    main()
