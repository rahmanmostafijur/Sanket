"""Profile validation (untrusted input) and the embedding text and hashes."""

from typing import Any

import pytest
from pydantic import ValidationError

from sanket.profiles import criteria as limits
from sanket.profiles.criteria import ProfileCriteria, ProfileWrite, criteria_of
from sanket.profiles.text import (
    EMBEDDING_TASK,
    build_profile_text,
    content_hash,
    profile_embedding_hash,
)


def write(**fields: Any) -> ProfileWrite:
    body: dict[str, Any] = {"name": "Backend", "summary": "backend work"}
    body.update(fields)
    return ProfileWrite.model_validate(body)


# --- validation ---------------------------------------------------------------------------


def test_a_minimal_profile_gets_empty_defaults() -> None:
    profile = write()

    assert profile.active is True
    assert profile.desired_titles == [] and profile.min_score_override is None


def test_a_profile_must_say_something() -> None:
    with pytest.raises(ValidationError, match="at least a desired title"):
        ProfileWrite.model_validate({"name": "Empty"})
    with pytest.raises(ValidationError):
        write(summary="   ")


@pytest.mark.parametrize("field", ["desired_titles", "required_skills", "preferred_skills"])
def test_a_single_skill_or_title_is_enough(field: str) -> None:
    assert write(summary="", **{field: ["Python"]})


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        write(salary=100)


def test_text_lists_are_cleaned_and_deduplicated_ignoring_case() -> None:
    profile = write(required_skills=["  Python ", "python", "Machine   Learning", "", "PYTHON"])

    assert profile.required_skills == ["Python", "Machine Learning"]


def test_the_name_is_trimmed_and_must_not_be_blank() -> None:
    assert write(name="  My   profile ").name == "My profile"
    with pytest.raises(ValidationError):
        write(name="   ")
    with pytest.raises(ValidationError):
        write(name="")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "x" * (limits.MAX_NAME_CHARS + 1)),
        ("summary", "x" * (limits.MAX_SUMMARY_CHARS + 1)),
        ("desired_titles", ["x" * (limits.MAX_TITLE_CHARS + 1)]),
        ("desired_titles", [f"t{i}" for i in range(limits.MAX_TITLES + 1)]),
        ("required_skills", ["x" * (limits.MAX_SKILL_CHARS + 1)]),
        ("required_skills", [f"s{i}" for i in range(limits.MAX_REQUIRED_SKILLS + 1)]),
        ("preferred_skills", [f"s{i}" for i in range(limits.MAX_PREFERRED_SKILLS + 1)]),
        ("locations", ["x" * (limits.MAX_LOCATION_CHARS + 1)]),
        ("locations", [f"l{i}" for i in range(limits.MAX_LOCATIONS + 1)]),
        ("countries", ["DE"] * (limits.MAX_COUNTRIES + 1)),
    ],
)
def test_every_text_and_list_has_a_bound(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        write(**{field: value})


def test_the_bounds_are_inclusive() -> None:
    profile = write(
        name="n" * limits.MAX_NAME_CHARS,
        summary="s" * limits.MAX_SUMMARY_CHARS,
        required_skills=[f"{i:02d}".ljust(limits.MAX_SKILL_CHARS, "x") for i in range(20)],
    )

    assert len(profile.required_skills) == limits.MAX_REQUIRED_SKILLS


@pytest.mark.parametrize("field", ["name", "summary", "desired_titles", "locations"])
def test_a_nul_character_is_refused(field: str) -> None:
    value: Any = ["a\x00b"] if field in ("desired_titles", "locations") else "a\x00b"

    with pytest.raises(ValidationError, match="NUL"):
        write(**{field: value})


def test_countries_are_uppercased_validated_and_deduplicated() -> None:
    assert write(countries=["de", "SE", " de"]).countries == ["DE", "SE"]
    for bad in ("XX", "DEU", "1", "", "D E"):
        with pytest.raises(ValidationError):
            write(countries=[bad])


def test_enum_lists_take_known_values_only_and_not_unknown() -> None:
    profile = write(
        seniorities=["junior", "mid", "junior"],
        work_modes=["remote"],
        employment_types=["contract"],
    )

    assert [level.value for level in profile.seniorities] == ["junior", "mid"]
    for field, bad in (
        ("seniorities", "expert"),
        ("work_modes", "unknown"),
        ("seniorities", "unknown"),
        ("employment_types", "unknown"),
    ):
        with pytest.raises(ValidationError):
            write(**{field: [bad]})


@pytest.mark.parametrize("score", [-0.1, 1.1, "high"])
def test_the_score_override_must_be_between_zero_and_one(score: Any) -> None:
    with pytest.raises(ValidationError):
        write(min_score_override=score)


def test_non_string_entries_are_refused_not_coerced() -> None:
    with pytest.raises(ValidationError):
        write(required_skills=[1, 2])
    with pytest.raises(ValidationError):
        write(summary=["a"])


# --- text and hashes ------------------------------------------------------------------------


def test_the_embedding_text_has_one_line_per_field_that_is_set() -> None:
    profile = write(
        summary="I build APIs",
        desired_titles=["Backend Engineer", "Platform Engineer"],
        required_skills=["Python", "SQL"],
        preferred_skills=["Go"],
        seniorities=["mid", "senior"],
        work_modes=["remote"],
        employment_types=["full_time"],
        countries=["DE", "SE"],
        locations=["Berlin", "Stockholm"],
    )

    expected = [
        "Looking for: I build APIs",
        "Desired titles: Backend Engineer; Platform Engineer",
        "Required skills: Python, SQL",
        "Preferred skills: Go",
        "Seniority: mid, senior",
        "Work mode: remote",
        "Employment type: full time",
        "Countries: DE, SE",
        "Locations: Berlin; Stockholm",
    ]

    assert build_profile_text(criteria_of(profile)) == "\n".join(expected)


def test_empty_fields_leave_no_line_and_the_name_is_not_embedded() -> None:
    text = build_profile_text(
        criteria_of(write(name="Secret name", summary="", required_skills=["Go"]))
    )

    assert text == "Required skills: Go"


def test_the_content_hash_ignores_the_name_and_the_order_of_list_entries() -> None:
    a = criteria_of(write(name="A", required_skills=["Go", "Python"], countries=["DE", "SE"]))
    b = criteria_of(write(name="B", required_skills=["python", "Go"], countries=["SE", "DE"]))
    c = criteria_of(write(name="A", required_skills=["Go"], countries=["DE", "SE"]))

    assert content_hash(a, True) == content_hash(a, True)
    assert content_hash(a, True) != content_hash(b, True)  # "Python" and "python" differ in case
    same_order = criteria_of(
        write(name="B", required_skills=["Python", "Go"], countries=["SE", "DE"])
    )
    assert content_hash(a, True) == content_hash(same_order, True)
    assert content_hash(a, True) != content_hash(c, True)


def test_active_is_part_of_the_content_hash() -> None:
    criteria = criteria_of(write())

    assert content_hash(criteria, True) != content_hash(criteria, False)


def test_every_criterion_changes_the_content_hash() -> None:
    base = criteria_of(write())
    variants = [
        write(summary="something else"),
        write(desired_titles=["x"]),
        write(required_skills=["x"]),
        write(preferred_skills=["x"]),
        write(seniorities=["mid"]),
        write(work_modes=["remote"]),
        write(employment_types=["contract"]),
        write(countries=["DE"]),
        write(locations=["Berlin"]),
        write(min_score_override=0.7),
    ]

    hashes = {content_hash(criteria_of(v), True) for v in variants} | {content_hash(base, True)}
    assert len(hashes) == len(variants) + 1


def test_the_embedding_hash_depends_on_text_model_version_and_dimension() -> None:
    base = profile_embedding_hash("text", "model", "1", 768)

    assert base == profile_embedding_hash("text", "model", "1", 768)
    assert len({base, profile_embedding_hash("other", "model", "1", 768)}) == 2
    assert profile_embedding_hash("text", "model-b", "1", 768) != base
    assert profile_embedding_hash("text", "model", "2", 768) != base
    assert profile_embedding_hash("text", "model", "1", 512) != base
    assert EMBEDDING_TASK == "query"


def test_criteria_of_drops_the_name_and_flag() -> None:
    criteria = criteria_of(write(name="Hidden", active=False))

    assert isinstance(criteria, ProfileCriteria)
    assert "name" not in criteria.model_dump() and "active" not in criteria.model_dump()
