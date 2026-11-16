"""Re-derive the normalized posting fields from each posting's stored raw payload.

Run with `python -m sanket.backfill_normalized`. The default is a dry run that only
counts what would change; pass --apply to write. Only rows whose normalized fields are
NULL or differ from what the source adapter derives are touched, and only those fields:
`content_hash`, `raw` and `updated_at` are never changed. Safe to run repeatedly.
"""

import argparse
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, Row, bindparam, select, update

from sanket.db import engine
from sanket.models import Posting
from sanket.sources import greenhouse, himalayas, jobicy, lever, remoteok, remotive, weworkremotely
from sanket.sources.base import NormalizedPosting
from sanket.storage import NORMALIZED_FIELDS

DEFAULT_BATCH_SIZE = 500
ROW_ID_PARAM = "row_id"
NEW_VALUE_PREFIX = "new_"

logger = logging.getLogger(__name__)

Converter = Callable[[str, dict], NormalizedPosting]


def _board_item(to_posting: Callable[[str, dict], NormalizedPosting]) -> Converter:
    """Greenhouse and Lever ids are "<board>:<id>"; the adapter needs the board part."""

    def convert(source_id: str, raw: dict) -> NormalizedPosting:
        board, _, _ = source_id.partition(":")
        return to_posting(board, raw)

    return convert


def _item(to_posting: Callable[[dict], NormalizedPosting]) -> Converter:
    return lambda source_id, raw: to_posting(raw)


CONVERTERS: dict[str, Converter] = {
    "greenhouse": _board_item(greenhouse.to_posting),
    "lever": _board_item(lever.to_posting),
    "himalayas": _item(himalayas.to_posting),
    "jobicy": _item(jobicy.to_posting),
    "weworkremotely": _item(weworkremotely.to_posting),
    "remoteok": _item(remoteok.to_posting),
    "remotive": _item(remotive.to_posting),
}


@dataclass(frozen=True)
class BackfillSummary:
    scanned: int = 0
    changed: int = 0
    applied: bool = False
    unknown_source: int = 0
    failed: int = 0

    def line(self) -> str:
        mode = "apply" if self.applied else "dry-run"
        return (
            f"backfill_normalized mode={mode} scanned={self.scanned} changed={self.changed} "
            f"unknown_source={self.unknown_source} failed={self.failed}"
        )


def _select_batch(after_id: int, batch_size: int):
    stored = [getattr(Posting, name) for name in NORMALIZED_FIELDS]
    return (
        select(Posting.id, Posting.source, Posting.source_id, Posting.raw, *stored)
        .where(Posting.id > after_id)
        .order_by(Posting.id)
        .limit(batch_size)
    )


def _is_current(row: Row, derived: NormalizedPosting) -> bool:
    return all(getattr(row, name) == getattr(derived, name) for name in NORMALIZED_FIELDS)


def _write(conn: Connection, derived_by_id: dict[int, NormalizedPosting]) -> None:
    stmt = update(Posting).where(Posting.id == bindparam(ROW_ID_PARAM))
    stmt = stmt.values({name: bindparam(NEW_VALUE_PREFIX + name) for name in NORMALIZED_FIELDS})
    params = [
        {
            ROW_ID_PARAM: posting_id,
            **{NEW_VALUE_PREFIX + name: getattr(derived, name) for name in NORMALIZED_FIELDS},
        }
        for posting_id, derived in derived_by_id.items()
    ]
    conn.execute(stmt, params)


def backfill(
    db_engine: Engine, apply: bool = False, batch_size: int = DEFAULT_BATCH_SIZE
) -> BackfillSummary:
    scanned = changed = unknown_source = failed = 0
    last_id = 0
    while True:
        with db_engine.begin() as conn:
            rows = conn.execute(_select_batch(last_id, batch_size)).all()
            if not rows:
                break
            to_write: dict[int, NormalizedPosting] = {}
            for row in rows:
                scanned += 1
                convert = CONVERTERS.get(row.source)
                if convert is None:
                    unknown_source += 1
                    logger.warning("posting %d: no adapter for source %r", row.id, row.source)
                    continue
                try:
                    derived = convert(row.source_id, row.raw)
                except (KeyError, TypeError, ValueError) as error:
                    failed += 1
                    logger.warning("posting %d: cannot derive fields: %r", row.id, error)
                    continue
                if not _is_current(row, derived):
                    changed += 1
                    to_write[row.id] = derived
            if apply and to_write:
                _write(conn, to_write)
            last_id = rows[-1].id
    return BackfillSummary(scanned, changed, apply, unknown_source, failed)


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
    args = parse_args(argv)
    summary = backfill(engine, apply=args.apply, batch_size=args.batch_size)
    logger.info(summary.line())
    if not args.apply:
        logger.info("dry run: nothing was written; pass --apply to write")


if __name__ == "__main__":
    main()
