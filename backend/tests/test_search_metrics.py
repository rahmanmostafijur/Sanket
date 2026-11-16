"""Ranking metrics against hand-computed values."""

import math

import pytest

from sanket.search.metrics import (
    QueryMetrics,
    aggregate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_query,
)

LOG2_3 = math.log2(3)
LOG2_4 = math.log2(4)
LOG2_5 = math.log2(5)


# --- recall ------------------------------------------------------------------------------


def test_recall_is_the_share_of_relevant_jobs_found_in_the_top_k() -> None:
    grades = {"a": 3, "b": 1, "c": 2}

    assert recall_at_k(["x", "a", "y", "c"], grades, k=4) == pytest.approx(2 / 3)
    assert recall_at_k(["x", "a", "y", "c"], grades, k=2) == pytest.approx(1 / 3)
    assert recall_at_k(["a", "b", "c"], grades, k=3) == 1.0
    assert recall_at_k(["x", "y"], grades, k=2) == 0.0


def test_recall_ignores_the_grade_and_counts_every_relevant_job_once() -> None:
    assert recall_at_k(["a", "a", "a"], {"a": 1, "b": 3}, k=3) == pytest.approx(0.5)


def test_recall_with_fewer_results_than_k() -> None:
    assert recall_at_k(["a"], {"a": 2, "b": 2}, k=10) == pytest.approx(0.5)


def test_recall_without_relevant_jobs_is_undefined() -> None:
    assert recall_at_k(["a"], {}, k=5) is None


# --- precision ---------------------------------------------------------------------------


def test_precision_divides_by_k_even_when_fewer_results_come_back() -> None:
    grades = {"a": 1, "c": 1}

    assert precision_at_k(["a", "b", "c", "d"], grades, k=4) == pytest.approx(0.5)
    assert precision_at_k(["a", "b"], grades, k=4) == pytest.approx(0.25)
    assert precision_at_k([], grades, k=4) == 0.0


def test_precision_counts_a_repeated_result_once() -> None:
    assert precision_at_k(["a", "a", "a", "a"], {"a": 1}, k=4) == pytest.approx(0.25)


def test_precision_without_relevant_jobs_is_undefined() -> None:
    assert precision_at_k(["a"], {}, k=3) is None


# --- reciprocal rank ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ranked", "expected"),
    [
        (["a", "x"], 1.0),
        (["x", "a"], 0.5),
        (["x", "y", "b"], 1 / 3),
        (["x", "y", "z"], 0.0),
        ([], 0.0),
    ],
)
def test_reciprocal_rank_is_one_over_the_rank_of_the_first_relevant_job(
    ranked: list[str], expected: float
) -> None:
    assert reciprocal_rank(ranked, {"a": 1, "b": 3}, k=3) == pytest.approx(expected)


def test_reciprocal_rank_only_looks_inside_the_top_k() -> None:
    assert reciprocal_rank(["x", "y", "a"], {"a": 3}, k=2) == 0.0


def test_reciprocal_rank_without_relevant_jobs_is_undefined() -> None:
    assert reciprocal_rank(["a"], {}, k=3) is None


# --- nDCG --------------------------------------------------------------------------------


def test_ndcg_of_the_ideal_order_is_one() -> None:
    assert ndcg_at_k(["c", "a", "b"], {"a": 2, "b": 1, "c": 3}, k=3) == pytest.approx(1.0)


def test_ndcg_with_gain_two_to_the_grade_minus_one_and_log2_discount() -> None:
    # Grades a=3 (gain 7), b=1 (gain 1). Ranking [b, x, a]:
    #   DCG  = 1/log2(2) + 0/log2(3) + 7/log2(4) = 1 + 3.5 = 4.5
    #   IDCG = 7/log2(2) + 1/log2(3)             = 7 + 0.63093 = 7.63093
    expected = (1 + 7 / LOG2_4) / (7 + 1 / LOG2_3)
    assert ndcg_at_k(["b", "x", "a"], {"a": 3, "b": 1}, k=3) == pytest.approx(expected)
    assert expected == pytest.approx(0.5897, abs=1e-4)


def test_ndcg_cuts_both_dcg_and_ideal_dcg_at_k() -> None:
    # k=2 with three relevant jobs: ideal is [a(3), b(2)] = 7 + 3/log2(3).
    grades = {"a": 3, "b": 2, "c": 1}
    ideal = 7 + 3 / LOG2_3
    assert ndcg_at_k(["c", "x", "a", "b"], grades, k=2) == pytest.approx((1 / 1) / ideal)
    assert ndcg_at_k(["b", "a"], grades, k=2) == pytest.approx((3 + 7 / LOG2_3) / ideal)


def test_ndcg_with_fewer_results_than_k_counts_missing_positions_as_misses() -> None:
    # Only one result of the two relevant jobs: DCG = 3/log2(2)... grade 2 -> gain 3.
    grades = {"a": 2, "b": 2}
    assert ndcg_at_k(["a"], grades, k=10) == pytest.approx(3 / (3 + 3 / LOG2_3))


def test_ndcg_of_equal_grades_does_not_depend_on_which_job_comes_first() -> None:
    grades = {"a": 2, "b": 2}
    assert ndcg_at_k(["a", "b"], grades, k=2) == ndcg_at_k(["b", "a"], grades, k=2) == 1.0


def test_ndcg_counts_a_repeated_result_only_at_its_first_position() -> None:
    # Position 2 and 3 repeat "a": they must not earn the gain again.
    assert ndcg_at_k(["a", "a", "a"], {"a": 1, "b": 1}, k=3) == pytest.approx(1 / (1 + 1 / LOG2_3))


def test_ndcg_with_no_hit_is_zero() -> None:
    assert ndcg_at_k(["x", "y"], {"a": 3}, k=2) == 0.0


def test_ndcg_without_relevant_jobs_is_undefined() -> None:
    assert ndcg_at_k(["a"], {}, k=3) is None


@pytest.mark.parametrize("k", [0, -1])
def test_k_must_be_positive(k: int) -> None:
    with pytest.raises(ValueError, match="k"):
        ndcg_at_k(["a"], {"a": 1}, k=k)
    with pytest.raises(ValueError, match="k"):
        recall_at_k(["a"], {"a": 1}, k=k)


def test_a_grade_outside_one_to_three_is_rejected() -> None:
    with pytest.raises(ValueError, match="grade"):
        ndcg_at_k(["a"], {"a": 0}, k=3)
    with pytest.raises(ValueError, match="grade"):
        recall_at_k(["a"], {"a": 4}, k=3)


# --- per query and aggregates ------------------------------------------------------------


def test_score_query_bundles_the_metrics() -> None:
    result = score_query(["x", "a", "b"], {"a": 3, "b": 1, "c": 2}, k=3)

    assert result.scored
    assert result.relevant_count == 3
    assert result.retrieved_count == 3
    assert result.recall == pytest.approx(2 / 3)
    assert result.precision == pytest.approx(2 / 3)
    assert result.reciprocal_rank == pytest.approx(0.5)
    expected = (7 / LOG2_3 + 1 / LOG2_4) / (7 + 3 / LOG2_3 + 1 / LOG2_4)
    assert result.ndcg == pytest.approx(expected)


def test_a_query_without_relevant_jobs_is_not_scored() -> None:
    result = score_query(["a"], {}, k=3)

    assert not result.scored
    assert result.relevant_count == 0
    assert (result.recall, result.precision, result.reciprocal_rank, result.ndcg) == (
        None,
        None,
        None,
        None,
    )


def test_aggregate_averages_scored_queries_and_reports_the_excluded_ones() -> None:
    perfect = score_query(["a"], {"a": 3}, k=3)
    missed = score_query(["x"], {"a": 3}, k=3)
    unlabelled = score_query(["a"], {}, k=3)

    summary = aggregate([perfect, missed, unlabelled])

    assert summary.queries_scored == 2
    assert summary.queries_excluded == 1
    assert summary.mean_recall == pytest.approx(0.5)
    assert summary.mean_reciprocal_rank == pytest.approx(0.5)
    assert summary.mean_ndcg == pytest.approx(0.5)
    assert summary.mean_precision == pytest.approx((1 / 3 + 0) / 2)


def test_aggregate_of_nothing_scored_has_no_means() -> None:
    summary = aggregate([score_query(["a"], {}, k=3)])

    assert summary.queries_scored == 0
    assert summary.queries_excluded == 1
    assert summary.mean_recall is None
    assert summary.mean_ndcg is None
    assert aggregate([]).queries_scored == 0


def test_every_metric_lies_between_zero_and_one() -> None:
    results: list[QueryMetrics] = [
        score_query(ranked, {"a": 3, "b": 2, "c": 1}, k=3)
        for ranked in (["a", "b", "c"], ["c", "x", "a"], ["x", "y", "z"], [], ["a", "a", "a"])
    ]

    for result in results:
        for value in (result.recall, result.precision, result.reciprocal_rank, result.ndcg):
            assert value is not None
            assert 0.0 <= value <= 1.0
