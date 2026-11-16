"""Reciprocal Rank Fusion of ranked candidate lists.

The score of a document is the weighted sum, over the lists it appears in, of
`1 / (k + rank)`, where rank is its 1-based position in that list. Only positions are used:
a full-text score (`ts_rank_cd`) and a cosine distance live on unrelated scales, so adding
or averaging them would let one list drown the other. `k` flattens the curve: a large `k`
makes the top few ranks matter less relative to the rest (60 is the value from the original
paper and the common default).

Pure and deterministic: no database, no clock. Ties are broken by the best rank the
document has in any list, then by job id, so equal inputs always give the same order.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class FusedItem:
    job_id: int
    score: float
    # The 1-based rank in each input list (in input order), None where it is absent.
    ranks: tuple[int | None, ...]

    @property
    def best_rank(self) -> int:
        return min(rank for rank in self.ranks if rank is not None)


def _validated_weights(weights: Sequence[float] | None, list_count: int) -> list[float]:
    if weights is None:
        return [1.0] * list_count
    if len(weights) != list_count:
        raise ValueError(f"expected {list_count} weights, got {len(weights)}")
    for weight in weights:
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"weight must be a finite number of at least 0, got {weight}")
    return [float(weight) for weight in weights]


def _first_ranks(items: Sequence[int]) -> dict[int, int]:
    """Job id -> 1-based rank of its first (best) occurrence; later duplicates are ignored."""
    ranks: dict[int, int] = {}
    for position, job_id in enumerate(items, 1):
        ranks.setdefault(job_id, position)
    return ranks


def rrf_fuse(
    rank_lists: Sequence[Sequence[int]],
    k: int = DEFAULT_RRF_K,
    weights: Sequence[float] | None = None,
) -> list[FusedItem]:
    """Fuse lists of job ids, each best first, into one list, best first.

    A duplicated id within one list counts once, at its best rank. A list with weight 0 is
    ignored (its ids do not appear unless another list has them). Inputs are not modified.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    used_weights = _validated_weights(weights, len(rank_lists))
    per_list = [_first_ranks(items) for items in rank_lists]

    scores: dict[int, float] = {}
    for ranks, weight in zip(per_list, used_weights, strict=True):
        if weight == 0:
            continue
        for job_id, rank in ranks.items():
            scores[job_id] = scores.get(job_id, 0.0) + weight / (k + rank)

    fused = [
        FusedItem(job_id, score, tuple(ranks.get(job_id) for ranks in per_list))
        for job_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.best_rank, item.job_id))
    return fused
