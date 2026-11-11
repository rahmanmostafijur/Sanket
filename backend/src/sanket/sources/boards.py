"""Shared loop for sources that read one public job board per company."""

import logging
import re
from collections.abc import Callable, Sequence

from sanket.sources.base import FetchResult, NormalizedPosting
from sanket.sources.http import BudgetExceededError

BOARD_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

logger = logging.getLogger(__name__)


def valid_slugs(source: str, slugs: Sequence[str]) -> list[str]:
    """Keep only slugs that are safe to put in a URL path; warn about the rest."""
    valid = [slug for slug in slugs if BOARD_SLUG.match(slug)]
    for slug in sorted(set(slugs) - set(valid)):
        logger.warning("%s: ignoring invalid board slug %r", source, slug)
    return valid


def collect_boards(
    source: str,
    boards: Sequence[str],
    fetch_board: Callable[[str], list[NormalizedPosting]],
) -> FetchResult:
    """Fetch every board; one failing board is logged and counted, the rest continue.

    Raises if every board failed, so the whole source is reported as failed.
    """
    if not boards:
        logger.info("%s: no boards configured", source)
    postings: list[NormalizedPosting] = []
    failed = 0
    for index, board in enumerate(boards):
        try:
            postings.extend(fetch_board(board))
        except BudgetExceededError:
            if index == 0:
                raise
            skipped = len(boards) - index
            logger.warning("%s: request budget reached, skipped %d boards", source, skipped)
            return FetchResult(postings, failed=failed, skipped=skipped)
        except Exception:
            logger.exception("%s: board %s failed", source, board)
            failed += 1
    if boards and failed == len(boards):
        raise RuntimeError(f"{source}: all {failed} boards failed")
    return FetchResult(postings, failed=failed)
