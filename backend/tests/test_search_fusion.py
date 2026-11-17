import math

import pytest

from sanket.search.fusion import FusedItem, rrf_fuse


def ids(items: list[FusedItem]) -> list[int]:
    return [item.job_id for item in items]


def test_two_lists_are_fused_on_rank_with_a_hand_computed_score() -> None:
    # k=60. List 1 is [1, 2, 3] and list 2 is [2, 4, 1].
    fused = rrf_fuse([[1, 2, 3], [2, 4, 1]], k=60)
    scores = {item.job_id: item.score for item in fused}

    assert scores[1] == pytest.approx(1 / 61 + 1 / 63)
    assert scores[2] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[3] == pytest.approx(1 / 63)
    assert scores[4] == pytest.approx(1 / 62)
    assert ids(fused) == [2, 1, 4, 3]


def test_ranks_are_reported_per_list() -> None:
    fused = rrf_fuse([[10, 20], [20, 30]])

    by_id = {item.job_id: item for item in fused}
    assert by_id[10].ranks == (1, None)
    assert by_id[20].ranks == (2, 1)
    assert by_id[30].ranks == (None, 2)


def test_only_ranks_matter_not_how_far_apart_the_original_scores_were() -> None:
    # The function takes no scores at all: the order alone decides.
    assert ids(rrf_fuse([[5, 6, 7]])) == [5, 6, 7]


def test_a_document_in_one_list_only_scores_one_term() -> None:
    (only,) = rrf_fuse([[7], []], k=10)

    assert only.job_id == 7
    assert only.score == pytest.approx(1 / 11)
    assert only.ranks == (1, None)


def test_a_document_in_both_lists_beats_one_in_a_single_list_at_the_same_rank() -> None:
    fused = rrf_fuse([[1, 2], [3, 2]])

    assert ids(fused)[0] == 2


def test_empty_input_gives_empty_output() -> None:
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_ties_break_by_best_rank_then_job_id() -> None:
    # 5 is rank 1 in list 1 only; 9 is rank 1 in list 2 only: equal score, equal best rank,
    # so the lower id wins.
    assert ids(rrf_fuse([[5], [9]])) == [5, 9]
    assert ids(rrf_fuse([[9], [5]])) == [5, 9]


def test_equal_scores_with_equal_best_rank_fall_back_to_the_id() -> None:
    # k=1: jobs 8 and 9 both score 1/2 + 1/4 (ranks 1 and 3, in either order), job 7 scores 2/3.
    fused = rrf_fuse([[8, 7, 9], [9, 7, 8]], k=1)

    assert ids(fused) == [8, 9, 7]
    assert fused[0].score == fused[1].score


def test_equal_scores_prefer_the_better_best_rank_over_the_lower_id() -> None:
    # k=1, weights 1 and 0.5. Job 5 is rank 1 of list 2: 0.5 * 1/2 = 0.25. Job 1 is rank 3 of
    # list 1: 1/4 = 0.25. Same score; job 5 has the better best rank, so it comes first.
    fused = rrf_fuse([[7, 8, 1], [5]], k=1, weights=[1.0, 0.5])

    by_id = {item.job_id: item.score for item in fused}
    assert by_id[5] == by_id[1]
    assert ids(fused).index(5) < ids(fused).index(1)


def test_duplicate_ids_in_one_list_count_once_at_their_best_rank() -> None:
    fused = rrf_fuse([[1, 2, 1, 3]], k=60)

    assert ids(fused) == [1, 2, 3]
    assert fused[0].score == pytest.approx(1 / 61)
    assert fused[2].ranks == (4,)


def test_weights_scale_each_list() -> None:
    fused = rrf_fuse([[1], [2]], k=60, weights=[1.0, 2.0])

    assert ids(fused) == [2, 1]
    assert fused[0].score == pytest.approx(2 / 61)


def test_a_zero_weight_list_is_ignored() -> None:
    fused = rrf_fuse([[1, 2], [3]], weights=[1.0, 0.0])

    assert ids(fused) == [1, 2]


def test_default_weights_are_one() -> None:
    assert rrf_fuse([[1], [2]]) == rrf_fuse([[1], [2]], weights=[1.0, 1.0])


@pytest.mark.parametrize("k", [0, -1, -60])
def test_k_must_be_positive(k: int) -> None:
    with pytest.raises(ValueError, match="k"):
        rrf_fuse([[1]], k=k)


@pytest.mark.parametrize(
    "bad", [[1.0], [1.0, 1.0, 1.0], [1.0, -0.5], [math.nan, 1.0], [math.inf, 1]]
)
def test_bad_weights_are_rejected(bad: list[float]) -> None:
    with pytest.raises(ValueError, match="weight"):
        rrf_fuse([[1], [2]], weights=bad)


def test_inputs_are_not_modified() -> None:
    lists = [[3, 1, 2], [2, 3]]
    snapshot = [list(items) for items in lists]

    rrf_fuse(lists)

    assert lists == snapshot


def test_a_longer_list_keeps_deep_ranks_but_they_count_little() -> None:
    fused = rrf_fuse([list(range(1, 101)), [100]], k=60)

    assert fused[0].job_id == 100
    last = next(item for item in fused if item.job_id == 100)
    assert last.ranks == (100, 1)
