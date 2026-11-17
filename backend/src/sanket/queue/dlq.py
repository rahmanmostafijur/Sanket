"""Dead-letter store commands: `python -m sanket.queue.dlq list|requeue|purge`.

A task is dead-lettered when it used up its attempts or failed permanently (unknown task,
payload that is not valid JSON). `list` shows them, `requeue` queues a fresh copy with a full
set of attempts (use it after fixing the cause), `purge` deletes them.
"""

import argparse
import sys
from collections.abc import Callable, Sequence

from sanket.config import settings
from sanket.observability.logs import configure_logging
from sanket.queue.base import DeadLetter, DeadLetterStore
from sanket.queue.connection import task_queue_from_settings

DEFAULT_LIST_LIMIT = 100
MAX_PAYLOAD_CHARS = 120


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="show dead-lettered tasks")
    listing.add_argument("--limit", type=_positive_int, default=DEFAULT_LIST_LIMIT)
    for name, verb in (("requeue", "queue again"), ("purge", "delete")):
        sub = commands.add_parser(name, help=f"{verb} dead-lettered tasks")
        sub.add_argument("ids", nargs="*", help="dead letter ids (see `list`)")
        sub.add_argument("--all", action="store_true", help="every dead letter")
    return parser.parse_args(argv)


def describe(letter: DeadLetter) -> str:
    when = letter.failed_at.isoformat(timespec="seconds") if letter.failed_at else "-"
    payload = letter.payload
    if len(payload) > MAX_PAYLOAD_CHARS:
        payload = payload[:MAX_PAYLOAD_CHARS] + "..."
    return (
        f"{letter.id}\ttask={letter.task_name}\tkey={letter.key or '-'}\t"
        f"attempts={letter.attempts}\tfailed_at={when}\terror={letter.error}\tpayload={payload}"
    )


def _selected_ids(args: argparse.Namespace, store: DeadLetterStore) -> list[str] | None:
    if args.all and args.ids:
        raise SystemExit("give dead letter ids or --all, not both")
    if args.all:
        return [letter.id for letter in store.list_dead_letters(limit=sys.maxsize)]
    if not args.ids:
        raise SystemExit("give dead letter ids or --all")
    return list(args.ids)


def run(
    args: argparse.Namespace, store: DeadLetterStore, out: Callable[[str], None] = print
) -> int:
    """Run a parsed command against `store`; the process exit code."""
    if args.command == "list":
        letters = store.list_dead_letters(limit=args.limit)
        for letter in letters:
            out(describe(letter))
        out(f"{len(letters)} dead letters")
        return 0
    ids = _selected_ids(args, store)
    if args.command == "purge":
        out(f"purged {store.purge_dead_letters(ids)} dead letters")
        return 0
    missing = 0
    for dead_id in ids or []:
        try:
            result = store.requeue_dead_letter(dead_id)
        except KeyError:
            out(f"{dead_id}: no such dead letter")
            missing += 1
            continue
        out(f"{dead_id}: {result.value}")
    return 1 if missing else 0


def main(argv: Sequence[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    queue = task_queue_from_settings(settings)
    if queue is None:
        raise SystemExit("REDIS_URL is not set")
    raise SystemExit(run(args, queue))


if __name__ == "__main__":
    main()
