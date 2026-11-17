"""Run the task queue worker: embeds saved profiles and matches jobs and profiles.

`python -m sanket.worker` works the queue until it is stopped (Ctrl+C or SIGTERM finish the
task in progress first). `--burst` works until the queue is empty and exits, for tests and
development. It needs REDIS_URL; GEMINI_API_KEY is needed for the profile embedding task.

While it runs the worker writes a heartbeat key in Redis (ADR 0011). `--check` exits 0 when the
heartbeat of this worker is fresh and 1 otherwise: the container health check.
"""

import argparse
import sys
from collections.abc import Sequence

from sanket.config import settings
from sanket.observability.logs import configure_logging
from sanket.runtime_checks import ConfigError, check_worker
from sanket.worker.check import check_worker_alive


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
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 0 if this worker's heartbeat is fresh, 1 if not (the health check), then stop",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.check:
        status, reason = check_worker_alive(settings)
        sys.stdout.write(reason + "\n")
        raise SystemExit(status)
    configure_logging()
    try:
        check_worker(settings)
    except ConfigError as error:
        raise SystemExit(f"{error}") from None
    # Imported here so that `--check`, which runs every few seconds, does not load the queue
    # and matching code.
    from sanket.worker.run import run_worker

    run_worker(settings, burst=args.burst, simple=args.simple)


if __name__ == "__main__":
    main()
