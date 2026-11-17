"""Ranking metrics for search evaluation, with graded relevance.

A ranking is a list of job references, best first; the relevance judgements are a mapping from
reference to grade (1 = somewhat relevant, 2 = relevant, 3 = highly relevant). Jobs without a
judgement count as not relevant. Everything is pure and returns values in [0, 1].

- `recall_at_k`: relevant jobs in the top k divided by all relevant jobs.
- `precision_at_k`: relevant jobs in the top k divided by k. The denominator is always k, so a
  ranking shorter than k is penalised for the positions it did not fill.
- `reciprocal_rank`: 1 / rank of the first relevant job in the top k, 0 if there is none; its
  mean over queries is MRR.
- `ndcg_at_k`: DCG of the top k divided by the DCG of the ideal order (all relevant jobs,
  highest grade first, cut at k), with gain `2**grade - 1` and discount `1 / log2(rank + 1)`.

A reference that appears more than once counts only at its first position. A query with no
relevant jobs has no defined value for any of these (None): it is left out of the means and
reported as excluded, rather than counted as a perfect or a zero result.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_GRADE = 1
MAX_GRADE = 3


def _check(grades: Mapping[str, int], k: int) -> None:
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    for job_ref, grade in grades.items():
        if not MIN_GRADE <= grade <= MAX_GRADE:
            raise ValueError(
                f"grade must be {MIN_GRADE} to {MAX_GRADE}, got {grade} for {job_ref!r}"
            )


def _top_k(ranked: Sequence[str], k: int) -> list[str]:
    """The first k distinct references, in order."""
    seen: dict[str, None] = {}
    for job_ref in ranked:
        seen.setdefault(job_ref, None)
        if len(seen) == k:
            break
    return list(seen)


def _first_k(ranked: Sequence[str], k: int) -> list[str]:
    """The references at positions 1..k with repeats blanked out, so positions are kept."""
    seen: set[str] = set()
    top: list[str] = []
    for job_ref in ranked[:k]:
        top.append("" if job_ref in seen else job_ref)
        seen.add(job_ref)
    return top


def recall_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float | None:
    _check(grades, k)
    if not grades:
        return None
    found = sum(1 for job_ref in set(_first_k(ranked, k)) if job_ref in grades)
    return found / len(grades)


def precision_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float | None:
    _check(grades, k)
    if not grades:
        return None
    found = sum(1 for job_ref in set(_first_k(ranked, k)) if job_ref in grades)
    return found / k


def reciprocal_rank(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float | None:
    _check(grades, k)
    if not grades:
        return None
    for position, job_ref in enumerate(ranked[:k], 1):
        if job_ref in grades:
            return 1 / position
    return 0.0


def _gain(grade: int) -> int:
    return (1 << grade) - 1


def _dcg(gains: Sequence[int]) -> float:
    return sum(gain / math.log2(position + 1) for position, gain in enumerate(gains, 1))


def ndcg_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float | None:
    _check(grades, k)
    if not grades:
        return None
    gains = [_gain(grades.get(job_ref, 0)) if job_ref else 0 for job_ref in _first_k(ranked, k)]
    ideal = sorted((_gain(grade) for grade in grades.values()), reverse=True)[:k]
    return _dcg(gains) / _dcg(ideal)


@dataclass(frozen=True)
class QueryMetrics:
    relevant_count: int
    retrieved_count: int
    recall: float | None
    precision: float | None
    reciprocal_rank: float | None
    ndcg: float | None

    @property
    def scored(self) -> bool:
        """False for a query with no relevant jobs, which has no metric values."""
        return self.relevant_count > 0


def score_query(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> QueryMetrics:
    return QueryMetrics(
        relevant_count=len(grades),
        retrieved_count=len(_top_k(ranked, k)),
        recall=recall_at_k(ranked, grades, k),
        precision=precision_at_k(ranked, grades, k),
        reciprocal_rank=reciprocal_rank(ranked, grades, k),
        ndcg=ndcg_at_k(ranked, grades, k),
    )


@dataclass(frozen=True)
class Aggregate:
    """Means over the scored queries (MRR is `mean_reciprocal_rank`)."""

    queries_scored: int
    queries_excluded: int
    mean_recall: float | None
    mean_precision: float | None
    mean_reciprocal_rank: float | None
    mean_ndcg: float | None


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def aggregate(results: Sequence[QueryMetrics]) -> Aggregate:
    scored = [result for result in results if result.scored]
    return Aggregate(
        queries_scored=len(scored),
        queries_excluded=len(results) - len(scored),
        mean_recall=_mean([result.recall for result in scored]),
        mean_precision=_mean([result.precision for result in scored]),
        mean_reciprocal_rank=_mean([result.reciprocal_rank for result in scored]),
        mean_ndcg=_mean([result.ndcg for result in scored]),
    )
