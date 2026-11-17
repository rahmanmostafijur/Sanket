"""Embed profiles and re-run matching: `python -m sanket.matching embed-profiles|rematch`.

Both commands derive their work from the database, so they repair anything the queue lost
(Redis was down when a profile was saved, a worker was away). The default is a dry run that
only counts and lists what would be done; pass --apply to act. Acting queues tasks for the
worker (needs REDIS_URL), or with --inline runs them now in this process.

  embed-profiles   profiles that are pending, failed or lack a vector for the configured model
  rematch          --job ID | --profile ID | --all-jobs | --all-profiles [--since-days N]

--inline runs each task once, so a provider failure marks the profile `failed` at once instead
of being retried with backoff; rerun the command (or queue it) to try again. The exit code is
non-zero when anything failed or could not be queued.
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from sanket.config import Settings, settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingClient
from sanket.matching.config import config_from_settings
from sanket.matching.tasks import MatchTaskDeps, build_registry, gemini_client_from_settings
from sanket.matching.work import (
    WorkItem,
    describe,
    embed_work,
    job_exists,
    job_work,
    profile_work,
)
from sanket.queue.base import EnqueueResult, TaskContext, TaskQueue
from sanket.queue.connection import task_queue_from_settings
from sanket.queue.memory import InMemoryTaskQueue

logger = logging.getLogger(__name__)

EMBED = "embed-profiles"
REMATCH = "rematch"
DEFAULT_EMBED_LIMIT = 1000


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _add_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true", help="act (the default is a dry run)")
    parser.add_argument(
        "--inline", action="store_true", help="run the tasks now instead of queueing them"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    embed = commands.add_parser(EMBED, help="embed profiles that are pending or failed")
    embed.add_argument("--limit", type=_positive_int, default=DEFAULT_EMBED_LIMIT)
    _add_mode(embed)
    rematch = commands.add_parser(REMATCH, help="match jobs and profiles again")
    rematch.add_argument("--job", type=_positive_int, metavar="ID")
    rematch.add_argument("--profile", type=_positive_int, metavar="ID")
    rematch.add_argument("--all-jobs", action="store_true")
    rematch.add_argument("--all-profiles", action="store_true")
    rematch.add_argument(
        "--since-days",
        type=_positive_int,
        metavar="N",
        help="with --all-jobs or --all-profiles: only those changed in the last N days",
    )
    _add_mode(rematch)
    args = parser.parse_args(argv)
    if args.command == REMATCH:
        _check_rematch(parser, args)
    return args


def _check_rematch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    single = args.job is not None or args.profile is not None
    everything = args.all_jobs or args.all_profiles
    if not single and not everything:
        parser.error("give --job, --profile, --all-jobs or --all-profiles")
    if single and everything:
        parser.error("--job and --profile cannot be combined with --all-jobs or --all-profiles")
    if args.job is not None and args.profile is not None:
        parser.error("give --job or --profile, not both")
    if args.since_days is not None and not everything:
        parser.error("--since-days needs --all-jobs or --all-profiles")


@dataclass(frozen=True)
class CliContext:
    """What a command runs against; `main` builds it from the settings, tests pass fakes."""

    config: Settings
    queue: TaskQueue | None
    embedder: EmbeddingClient | None
    db_engine: Engine
    now: datetime


@dataclass(frozen=True)
class Outcome:
    selected: int = 0
    queued: int = 0
    duplicate: int = 0
    ran: int = 0
    failed: int = 0

    def line(self, command: str, mode: str) -> str:
        return (
            f"{command} mode={mode} selected={self.selected} queued={self.queued} "
            f"duplicate={self.duplicate} ran={self.ran} failed={self.failed}"
        )


def select_work(args: argparse.Namespace, ctx: CliContext) -> list[WorkItem]:
    spec = config_from_settings(ctx.config).spec
    with ctx.db_engine.connect() as conn:
        if args.command == EMBED:
            return embed_work(conn, spec, args.limit)
        since = ctx.now - timedelta(days=args.since_days) if args.since_days else None
        if args.job is not None:
            if not job_exists(conn, args.job):
                raise SystemExit(f"job {args.job} does not exist")
            return job_work(conn, spec, job_id=args.job)
        if args.profile is not None:
            items = profile_work(conn, spec, profile_id=args.profile)
            if not items:
                raise SystemExit(
                    f"profile {args.profile} does not exist or is not embedded yet "
                    f"(python -m sanket.matching {EMBED})"
                )
            return items
        items = job_work(conn, spec, since=since) if args.all_jobs else []
        return items + (profile_work(conn, spec, since=since) if args.all_profiles else [])


def _queue_items(queue: TaskQueue, items: Sequence[WorkItem]) -> Outcome:
    queued = duplicate = 0
    for position, item in enumerate(items):
        try:
            result = queue.enqueue(item.task_name, item.payload, key=item.key)
        except Exception:  # the queue backend may fail in any way
            logger.exception("Queueing stopped after %d of %d tasks", position, len(items))
            return Outcome(len(items), queued, duplicate, failed=len(items) - position)
        if result is EnqueueResult.ENQUEUED:
            queued += 1
        else:
            duplicate += 1
    return Outcome(len(items), queued, duplicate)


def _run_inline(items: Sequence[WorkItem], ctx: CliContext) -> Outcome:
    """Run the items here, and the tasks they chain (a profile embedded is then matched)."""
    chained = InMemoryTaskQueue()
    registry = build_registry(
        MatchTaskDeps(
            cfg=config_from_settings(ctx.config),
            embedder=ctx.embedder,
            queue=chained,
            db_engine=ctx.db_engine,
        )
    )
    for item in items:
        chained.enqueue(item.task_name, item.payload, key=item.key)
    ran = failed = 0
    while tasks := chained.take_all():
        for task in tasks:
            try:
                registry.get(task.task_name)(
                    task.payload, TaskContext(task.task_name, task.key, 1, 1)
                )
            except Exception:  # one failing task must not stop the others
                failed += 1
                logger.exception("Task %s (key %s) failed", task.task_name, task.key)
            else:
                ran += 1
    return Outcome(len(items), ran=ran, failed=failed)


def execute(args: argparse.Namespace, ctx: CliContext) -> int:
    """Run a parsed command; the process exit code."""
    items = select_work(args, ctx)
    if not args.apply:
        logger.info("%s", Outcome(len(items)).line(args.command, "dry-run"))
        if items:
            logger.info("would run: %s", describe(items))
        logger.info("dry run: nothing was done; pass --apply to act")
        return 0
    if args.inline:
        if args.command == EMBED and ctx.embedder is None and items:
            raise SystemExit("GEMINI_API_KEY is not set: it is needed to embed inline")
        outcome = _run_inline(items, ctx)
        mode = "apply-inline"
    else:
        if ctx.queue is None:
            raise SystemExit("REDIS_URL is not set: use --inline to run the tasks now")
        outcome = _queue_items(ctx.queue, items)
        mode = "apply-queue"
    logger.info("%s", outcome.line(args.command, mode))
    return 1 if outcome.failed else 0


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    needs_queue = args.apply and not args.inline
    needs_embedder = args.apply and args.inline and args.command == EMBED
    ctx = CliContext(
        config=settings,
        queue=task_queue_from_settings(settings) if needs_queue else None,
        embedder=gemini_client_from_settings(settings) if needs_embedder else None,
        db_engine=engine,
        now=datetime.now(UTC),
    )
    raise SystemExit(execute(args, ctx))


if __name__ == "__main__":
    main()
