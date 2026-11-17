"""The scoring function, with hand-computed examples."""

import pytest

from sanket.matching.score import SCORER_VERSION, score_job_for_profile
from tests.match_helpers import config, job_view, profile_view

# With the default weights (cosine 0.6, skills 0.25, title 0.15) and min_cosine 0.5, a cosine
# of 0.75 is half way between the floor and 1, so its part is 0.5.
COSINE = 0.75


def score(
    job_kwargs: dict | None = None,
    profile_kwargs: dict | None = None,
    cosine: float = COSINE,
    **cfg,
):
    return score_job_for_profile(
        job_view(**(job_kwargs or {})),
        profile_view(**(profile_kwargs or {})),
        cosine,
        config(**cfg),
    )


def test_the_scorer_version_is_a_positive_integer() -> None:
    assert isinstance(SCORER_VERSION, int) and SCORER_VERSION >= 1


# --- the blend ----------------------------------------------------------------------------


def test_with_only_a_cosine_the_score_is_the_rescaled_cosine() -> None:
    result = score(cosine=0.8)

    # (0.8 - 0.5) / (1 - 0.5) = 0.6, the only part that applies
    assert result.score == pytest.approx(0.6)
    assert result.is_match is True
    assert result.components["skills"]["part"] is None
    assert result.components["title"]["part"] is None


def test_a_cosine_at_the_floor_scores_zero_and_one_scores_one() -> None:
    assert score(cosine=0.5).score == 0.0
    assert score(cosine=1.0).score == 1.0


def test_all_three_parts_are_blended_by_weight() -> None:
    result = score(
        profile_kwargs={
            "required_skills": ("Python", "SQL"),
            "preferred_skills": ("PostgreSQL",),
            "desired_titles": ("Backend Engineer",),
        },
        required_skills_min_fraction=0.5,
    )

    # cosine part 0.5; skills: required hit Python (1 of 2), preferred hit PostgreSQL (1 of 1):
    # (2*1 + 1) / (2*2 + 1) = 0.6; title: both words found = 1.0
    # (0.6*0.5 + 0.25*0.6 + 0.15*1.0) / (0.6 + 0.25 + 0.15) = 0.3 + 0.15 + 0.15 = 0.6
    assert result.score == pytest.approx(0.6)
    assert result.components["skills"]["part"] == pytest.approx(0.6)
    assert result.components["title"]["part"] == 1.0
    assert result.components["title"]["best"] == "Backend Engineer"
    assert result.is_match is True


def test_a_part_that_does_not_apply_is_left_out_and_the_weights_renormalised() -> None:
    result = score(profile_kwargs={"desired_titles": ("Backend Developer",)})

    # title part: one of two words ("backend") = 0.5; cosine part 0.5;
    # (0.6*0.5 + 0.15*0.5) / (0.6 + 0.15) = 0.5
    assert result.score == pytest.approx(0.5)
    assert result.is_match is False


def test_the_best_of_several_desired_titles_counts() -> None:
    result = score(profile_kwargs={"desired_titles": ("Data Scientist", "Backend Engineer")})

    assert result.components["title"]["part"] == 1.0
    assert result.components["title"]["best"] == "Backend Engineer"


def test_title_words_are_compared_ignoring_case_and_punctuation() -> None:
    result = score(
        job_kwargs={"title": "BACKEND-ENGINEER (Python)"},
        profile_kwargs={"desired_titles": ("backend engineer",)},
    )

    assert result.components["title"]["part"] == 1.0


def test_skills_are_compared_ignoring_case_and_spacing() -> None:
    result = score(
        job_kwargs={"skills": ("python", "Machine   Learning")},
        profile_kwargs={"preferred_skills": ("PYTHON", "machine learning", "Go")},
    )

    # 2 of 3 preferred skills
    assert result.components["skills"]["part"] == pytest.approx(2 / 3)
    assert result.components["skills"]["preferred_hits"] == ["PYTHON", "machine learning"]


def test_a_job_with_no_extracted_skills_is_not_judged_on_skills() -> None:
    result = score(
        job_kwargs={"skills": ()},
        profile_kwargs={"preferred_skills": ("Python",)},
    )

    assert result.components["skills"]["part"] is None
    assert result.components["skills"]["job_skills_known"] is False
    assert result.score == pytest.approx(0.5)


def test_weights_can_all_be_zero_without_dividing_by_zero() -> None:
    result = score(weight_cosine=0, weight_skills=0, weight_title=0)

    assert result.score == pytest.approx(0.5)


def test_the_score_stays_within_zero_and_one_for_any_cosine() -> None:
    for cosine in (-1.0, 0.0, 0.3, 0.5, 0.99, 1.0):
        assert 0.0 <= score(cosine=cosine).score <= 1.0


# --- thresholds ---------------------------------------------------------------------------


def test_a_score_just_below_the_threshold_is_not_a_match_and_at_it_is() -> None:
    # cosine 0.775 -> part 0.55
    assert score(cosine=0.7749).is_match is False
    assert score(cosine=0.775).is_match is True


def test_a_profile_can_override_the_threshold() -> None:
    strict = score(profile_kwargs={"min_score_override": 0.9}, cosine=0.8)
    lenient = score(profile_kwargs={"min_score_override": 0.1}, cosine=0.6)

    assert strict.is_match is False and strict.components["threshold"] == 0.9
    assert lenient.is_match is True


def test_a_cosine_below_the_minimum_is_never_a_match() -> None:
    # Strong skills and title cannot rescue a job whose embedding is too far away.
    result = score(
        profile_kwargs={"required_skills": ("Python",), "desired_titles": ("Backend Engineer",)},
        cosine=0.45,
        min_score=0.0,
    )

    assert result.passed_filters is True
    assert result.components["cosine"]["ok"] is False
    assert result.is_match is False


# --- filters ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "job_value", "wanted", "profile_field"),
    [
        ("seniority", "senior", frozenset({"senior", "lead"}), "seniorities"),
        ("work_mode", "remote", frozenset({"remote"}), "work_modes"),
        ("employment_type", "full_time", frozenset({"full_time"}), "employment_types"),
        ("country", "DE", frozenset({"DE", "SE"}), "countries"),
    ],
)
def test_a_known_value_in_the_wanted_set_passes(field, job_value, wanted, profile_field) -> None:
    result = score(job_kwargs={field: job_value}, profile_kwargs={profile_field: wanted})

    assert result.components["filters"][field] == "pass"
    assert result.passed_filters is True


@pytest.mark.parametrize(
    ("field", "job_value", "wanted", "profile_field"),
    [
        ("seniority", "junior", frozenset({"senior"}), "seniorities"),
        ("work_mode", "onsite", frozenset({"remote", "hybrid"}), "work_modes"),
        ("employment_type", "contract", frozenset({"full_time"}), "employment_types"),
        ("country", "BD", frozenset({"DE", "SE"}), "countries"),
    ],
)
def test_a_known_value_outside_the_wanted_set_fails_the_filter(
    field, job_value, wanted, profile_field
) -> None:
    result = score(
        job_kwargs={field: job_value}, profile_kwargs={profile_field: wanted}, cosine=1.0
    )

    assert result.components["filters"][field] == "fail"
    assert result.passed_filters is False
    assert result.is_match is False
    assert result.score > 0  # the score is still reported, to explain the rejection


@pytest.mark.parametrize(
    ("field", "profile_field", "wanted"),
    [
        ("seniority", "seniorities", frozenset({"senior"})),
        ("work_mode", "work_modes", frozenset({"remote"})),
        ("employment_type", "employment_types", frozenset({"full_time"})),
        ("country", "countries", frozenset({"DE"})),
    ],
)
def test_an_unknown_value_passes_the_filter_and_is_annotated(field, profile_field, wanted) -> None:
    result = score(job_kwargs={field: None}, profile_kwargs={profile_field: wanted}, cosine=0.9)

    assert result.components["filters"][field] == "unknown"
    assert result.components["unknown_fields"] == [field]
    assert result.passed_filters is True
    assert result.is_match is True


def test_a_filter_the_profile_does_not_set_is_not_applied() -> None:
    result = score(job_kwargs={"seniority": "junior", "work_mode": None})

    assert set(result.components["filters"].values()) == {"na"}
    assert result.components["unknown_fields"] == []


# --- required skills ----------------------------------------------------------------------


def test_every_required_skill_must_be_listed_by_default() -> None:
    profile = {"required_skills": ("Python", "Kubernetes")}

    result = score(profile_kwargs=profile, cosine=1.0)

    assert result.components["filters"]["required_skills"] == "fail"
    assert result.components["skills"]["required_missing"] == ["Kubernetes"]
    assert result.is_match is False


def test_a_lower_required_fraction_allows_some_missing_skills() -> None:
    profile = {"required_skills": ("Python", "PostgreSQL", "Kubernetes", "Go")}

    half = score(profile_kwargs=profile, required_skills_min_fraction=0.5)
    most = score(profile_kwargs=profile, required_skills_min_fraction=0.75)

    assert half.components["filters"]["required_skills"] == "pass"  # 2 of 4
    assert most.components["filters"]["required_skills"] == "fail"  # needs 3 of 4


def test_a_job_without_extracted_skills_passes_the_required_filter_annotated() -> None:
    result = score(job_kwargs={"skills": ()}, profile_kwargs={"required_skills": ("Python",)})

    assert result.components["filters"]["required_skills"] == "unknown"
    assert "required_skills" in result.components["unknown_fields"]
    assert result.passed_filters is True


# --- annotations and stability --------------------------------------------------------------


def test_location_match_is_reported_but_does_not_change_the_score() -> None:
    near = score(
        job_kwargs={"location": "Berlin, Germany"}, profile_kwargs={"locations": ("berlin",)}
    )
    far = score(job_kwargs={"location": "Dhaka"}, profile_kwargs={"locations": ("berlin",)})
    none = score(job_kwargs={"location": None}, profile_kwargs={"locations": ("berlin",)})
    unset = score(profile_kwargs={})

    assert (near.components["location_match"], far.components["location_match"]) == (True, False)
    assert none.components["location_match"] is None and unset.components["location_match"] is None
    assert near.score == far.score


def test_the_same_inputs_always_give_identical_results() -> None:
    profile = {"required_skills": ("Python",), "desired_titles": ("Engineer",)}

    assert score(profile_kwargs=profile) == score(profile_kwargs=profile)


def test_components_are_plain_json() -> None:
    import json

    result = score(profile_kwargs={"required_skills": ("Python",), "countries": frozenset({"DE"})})

    assert json.loads(json.dumps(result.components)) == result.components
