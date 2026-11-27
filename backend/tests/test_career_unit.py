"""The career profile's rules: values, schemas, completeness, years worked and the matching draft."""

from datetime import date
from typing import Annotated, Any

import pytest
from pydantic import TypeAdapter, ValidationError

from sanket.career import schemas
from sanket.career.completeness import completeness_of, personal_is_filled, years_of_experience
from sanket.career.fields import (
    clean_block,
    clean_country,
    clean_line,
    clean_url,
    format_month,
    parse_month,
)
from sanket.career.matching import NothingToDeriveError, derive_draft, seniorities_for
from sanket.career.store import CareerData

TODAY = date(2026, 6, 1)


def build(model: type[Any], **values: Any) -> Any:
    """A model built from request-style values (months as text), as a client would send them."""
    return model(**values)


def checked_link(host: str | None, raw: str) -> str:
    """A link run through the validator the schemas use."""
    return TypeAdapter(Annotated[str, clean_url(host)]).validate_python(raw)


def fails(model: type[Any], **values: Any) -> dict[str, str]:
    """The fields a model refuses, with their messages."""
    with pytest.raises(ValidationError) as caught:
        model(**values)
    return {".".join(str(part) for part in e["loc"]): e["msg"] for e in caught.value.errors()}


# --- values -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "month"),
    [
        ("2021-09", date(2021, 9, 1)),
        ("1950-01", date(1950, 1, 1)),
        (" 2024-12 ", date(2024, 12, 1)),
    ],
)
def test_a_month_is_year_and_month(text: str, month: date) -> None:
    assert parse_month(text) == month
    assert format_month(month) == text.strip()


@pytest.mark.parametrize(
    "text", ["2021", "2021-9", "2021-13", "2021-00", "1949-12", "Sept 2021", ""]
)
def test_anything_else_is_not_a_month(text: str) -> None:
    with pytest.raises(ValueError, match="YYYY-MM|between 01 and 12|1950"):
        parse_month(text)


def test_text_is_collapsed_and_control_characters_are_refused() -> None:
    assert clean_line("  Ada \n  Example ") == "Ada Example"
    assert clean_block("a  b \r\n\r\n\r\n\r\n c ") == "a b\n\nc"
    for bad in ("a\x00b", "a\x07b"):
        with pytest.raises(ValueError, match="control"):
            clean_line(bad)
        with pytest.raises(ValueError, match="control"):
            clean_block(bad)


@pytest.mark.parametrize(("raw", "code"), [("de", "DE"), (" bd ", "BD"), ("", "")])
def test_a_country_is_a_two_letter_code(raw: str, code: str) -> None:
    assert clean_country(raw) == code


@pytest.mark.parametrize("raw", ["XX", "Germany", "D", "DEU"])
def test_a_bad_country_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="two-letter"):
        clean_country(raw)


@pytest.mark.parametrize(
    ("raw", "link"),
    [
        ("github.com/ada", "https://github.com/ada"),
        ("https://www.github.com/ada", "https://www.github.com/ada"),
        ("http://github.com/ada?tab=repos", "http://github.com/ada?tab=repos"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_a_github_link_is_normalised(raw: str, link: str) -> None:
    assert checked_link("github.com", raw) == link


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com.evil.example/ada",
        "https://evilgithub.com/ada",
        "https://gitlab.com/ada",
        "https://user:secret@github.com/ada",
        "ftp://github.com/ada",
        "javascript:alert(1)",
        "mailto:ada@example.com",
        "https://localhost/ada",
        "https://github.com/a b",
        "https://github.com:notaport/ada",
        "https://github.com/" + "a" * 300,
    ],
)
def test_a_link_that_is_not_a_plain_github_page_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        checked_link("github.com", raw)


def test_any_site_is_fine_for_a_portfolio_but_a_port_is_kept() -> None:
    assert checked_link(None, "example.com:8080/work") == "https://example.com:8080/work"


# --- schemas ------------------------------------------------------------------------------


def test_personal_details_are_cleaned_and_all_optional() -> None:
    personal = schemas.PersonalWrite(
        full_name="  Ada   Example", country="de", summary="A\n\n\n\nB"
    )

    assert (personal.full_name, personal.country, personal.summary) == (
        "Ada Example",
        "DE",
        "A\n\nB",
    )
    assert schemas.PersonalWrite().model_dump() == {
        "full_name": "",
        "headline": "",
        "summary": "",
        "country": "",
        "city": "",
        "github_url": "",
        "linkedin_url": "",
        "portfolio_url": "",
        "availability": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "n" * 101),
        ("headline", "h" * 121),
        ("summary", "s" * 1001),
        ("city", "c" * 101),
        ("country", "Germany"),
        ("github_url", "https://gitlab.com/ada"),
        ("linkedin_url", "https://github.com/ada"),
        ("portfolio_url", "javascript:alert(1)"),
        ("availability", "whenever"),
        ("full_name", 7),
        ("full_name", None),
    ],
)
def test_invalid_personal_details_name_the_field(field: str, value: Any) -> None:
    assert field in fails(schemas.PersonalWrite, **{field: value})


def test_the_personal_section_has_no_room_for_what_must_not_be_collected() -> None:
    for name in (
        "date_of_birth",
        "gender",
        "religion",
        "marital_status",
        "address",
        "photo",
        "email",
    ):
        assert name in fails(schemas.PersonalWrite, **{name: "x"})
    assert set(schemas.PersonalWrite.model_fields) == {
        "full_name",
        "headline",
        "summary",
        "country",
        "city",
        "github_url",
        "linkedin_url",
        "portfolio_url",
        "availability",
    }


def test_the_longest_allowed_values_are_accepted() -> None:
    schemas.PersonalWrite(
        full_name="n" * 100, headline="h" * 120, summary="s" * 1000, city="c" * 100
    )
    build(
        schemas.ExperienceWrite,
        company="c" * 150,
        title="t" * 150,
        start="2020-01",
        end="2020-02",
        description="d" * 2000,
    )
    build(
        schemas.EducationWrite,
        institution="i" * 150,
        degree="d" * 100,
        field="f" * 100,
        start="2015-01",
        grade="g" * 50,
    )


def test_education_dates_are_ordered_and_not_in_the_future() -> None:
    assert (
        build(schemas.EducationWrite, institution="Example University", start="2015-09").end is None
    )
    assert "end" in fails(schemas.EducationWrite, institution="X", start="2016-01", end="2015-01")
    assert "start" in fails(schemas.EducationWrite, institution="X", start="2999-01")
    assert "end" in fails(schemas.EducationWrite, institution="X", start="2020-01", end="2999-01")
    assert "institution" in fails(schemas.EducationWrite, institution="  ", start="2015-01")
    assert "start" in fails(schemas.EducationWrite, institution="X")


def test_experience_either_ends_or_is_current() -> None:
    job: dict[str, Any] = {"company": "Example Corp", "title": "Engineer", "start": "2019-01"}

    assert build(schemas.ExperienceWrite, **job, current=True).end is None
    assert build(schemas.ExperienceWrite, **job, end="2020-01").current is False
    assert "end" in fails(schemas.ExperienceWrite, **job, current=True, end="2020-01")
    assert "end" in fails(schemas.ExperienceWrite, **job)
    assert "end" in fails(schemas.ExperienceWrite, **job, end="2018-12")
    assert "end" in fails(schemas.ExperienceWrite, **job, end="2999-01")
    assert "start" in fails(schemas.ExperienceWrite, **{**job, "start": "2999-01"}, current=True)


def test_skills_and_languages_have_levels_from_a_fixed_list() -> None:
    assert schemas.SkillWrite(name="Python").level is None
    assert "level" in fails(schemas.SkillWrite, name="Python", level="wizard")
    assert "proficiency" in fails(schemas.LanguageWrite, name="English")
    assert "proficiency" in fails(schemas.LanguageWrite, name="English", proficiency="godlike")
    assert "name" in fails(schemas.SkillWrite, name=" ")


def test_a_certification_year_is_bounded_and_its_link_checked() -> None:
    assert schemas.CertificationWrite(title="Exam", year=2022, url="example.com/cert").url == (
        "https://example.com/cert"
    )
    assert "year" in fails(schemas.CertificationWrite, title="Exam", year=1949)
    assert "year" in fails(schemas.CertificationWrite, title="Exam", year=2999)
    assert "url" in fails(schemas.CertificationWrite, title="Exam", url="ftp://example.com")


def test_a_project_description_is_bounded() -> None:
    schemas.ProjectWrite(title="Router", description="d" * 1000)
    assert "description" in fails(schemas.ProjectWrite, title="Router", description="d" * 1001)


def test_a_section_has_a_most_and_names_cannot_repeat() -> None:
    skill = {"name": "Python"}
    assert "items" in fails(schemas.SkillItems, items=[{"name": f"S{n}"} for n in range(61)])
    assert "items" in fails(schemas.SkillItems, items=[skill, {"name": "python"}])
    assert "items" in fails(
        schemas.LanguageItems,
        items=[
            {"name": "English", "proficiency": "native"},
            {"name": "ENGLISH", "proficiency": "basic"},
        ],
    )
    assert "items" in fails(
        schemas.EducationItems, items=[{"institution": "X", "start": "2015-01"}] * 11
    )
    assert "extra" in fails(schemas.SkillItems, items=[skill], extra=1)


# --- completeness and years worked -----------------------------------------------------------


def job(start: str, end: str | None, *, title: str = "Engineer", current: bool = False) -> Any:
    return build(
        schemas.ExperienceOut,
        id=1,
        company="Example Corp",
        title=title,
        start=start,
        current=current,
        end=end,
    )


def career(**sections: Any) -> CareerData:
    empty: dict[str, Any] = {
        "personal": schemas.PersonalWrite(),
        "education": [],
        "experience": [],
        "skills": [],
        "languages": [],
        "certifications": [],
        "projects": [],
    }
    return CareerData(**{**empty, **sections})


def test_an_empty_career_profile_is_zero_percent_and_names_every_section() -> None:
    result = completeness_of(career())

    assert result.percent == 0
    assert result.missing == [
        "personal",
        "education",
        "experience",
        "skills",
        "languages",
        "certifications",
        "projects",
    ]
    assert not any(result.sections.values())


def test_completeness_counts_filled_sections_and_names_the_rest() -> None:
    data = career(
        personal=schemas.PersonalWrite(
            full_name="Ada Example", headline="Engineer", summary="Builds APIs.", country="DE"
        ),
        skills=[schemas.SkillOut(id=1, name="Python")],
        experience=[job("2020-01", "2021-01")],
    )

    result = completeness_of(data)

    assert result.percent == 43
    assert (
        result.sections["personal"] and result.sections["skills"] and result.sections["experience"]
    )
    assert result.missing == ["education", "languages", "certifications", "projects"]


def test_a_fully_filled_profile_is_one_hundred_percent() -> None:
    data = career(
        personal=schemas.PersonalWrite(
            full_name="Ada", headline="Engineer", summary="Builds.", country="DE"
        ),
        education=[build(schemas.EducationOut, id=1, institution="X", start="2015-01")],
        experience=[job("2020-01", "2021-01")],
        skills=[schemas.SkillOut(id=1, name="Python")],
        languages=[schemas.LanguageOut(id=1, name="English", proficiency="fluent")],
        certifications=[schemas.CertificationOut(id=1, title="Exam")],
        projects=[schemas.ProjectOut(id=1, title="Router")],
    )

    result = completeness_of(data)

    assert (result.percent, result.missing) == (100, [])


@pytest.mark.parametrize("missing", ["full_name", "headline", "summary", "country"])
def test_the_personal_section_needs_all_four_to_count(missing: str) -> None:
    values = {"full_name": "Ada", "headline": "Engineer", "summary": "Builds.", "country": "DE"}
    values[missing] = ""

    assert not personal_is_filled(build(schemas.PersonalWrite, **values))


def test_no_jobs_means_no_years() -> None:
    assert years_of_experience([], TODAY) is None


@pytest.mark.parametrize(
    ("jobs", "years"),
    [
        ([job("2020-01", "2020-12")], 1.0),
        ([job("2020-01", "2020-01")], 0.1),
        ([job("2020-01", "2021-12")], 2.0),
        # Two jobs at the same time count once.
        ([job("2018-01", "2019-12"), job("2019-01", "2020-12")], 3.0),
        # One job inside another adds nothing.
        ([job("2018-01", "2021-12"), job("2019-01", "2019-12")], 4.0),
        # A gap is not worked time.
        ([job("2018-01", "2018-12"), job("2020-01", "2020-12")], 2.0),
        # Next to each other, no gap.
        ([job("2018-01", "2018-12"), job("2019-01", "2019-12")], 2.0),
        # A current job runs to this month (June 2026 here).
        ([job("2025-07", None, current=True)], 1.0),
    ],
)
def test_years_are_the_months_covered_by_at_least_one_job(jobs: list[Any], years: float) -> None:
    assert years_of_experience(jobs, TODAY) == years


# --- the matching draft ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("years", "levels"),
    [
        (None, []),
        (0.1, ["junior"]),
        (1.9, ["junior"]),
        (2.0, ["mid"]),
        (4.9, ["mid"]),
        (5.0, ["senior"]),
        (30, ["senior"]),
    ],
)
def test_seniority_follows_the_years_and_is_never_lead(
    years: float | None, levels: list[str]
) -> None:
    assert seniorities_for(years) == levels


def test_nothing_is_derived_from_a_profile_with_no_job_and_no_skill() -> None:
    with pytest.raises(NothingToDeriveError):
        derive_draft(career(personal=schemas.PersonalWrite(full_name="Ada", city="Berlin")))


def test_roles_are_the_latest_distinct_titles_and_at_most_three() -> None:
    data = career(
        experience=[
            job("2010-01", "2012-01", title="Junior Developer"),
            job("2012-02", "2015-01", title="Developer"),
            job("2015-02", "2018-01", title="Senior Developer"),
            job("2018-02", "2020-01", title="developer"),
            job("2020-02", None, title="Lead Developer", current=True),
        ]
    )

    assert derive_draft(data, TODAY).desired_titles == [
        "Lead Developer",
        "developer",
        "Senior Developer",
    ]


def test_the_headline_names_the_role_when_there_are_no_jobs() -> None:
    data = career(
        personal=schemas.PersonalWrite(headline="Backend engineer"),
        skills=[schemas.SkillOut(id=1, name="Python")],
    )

    assert derive_draft(data, TODAY).desired_titles == ["Backend engineer"]


def skill(n: int, level: Any = None) -> Any:
    return schemas.SkillOut(id=n, name=f"Skill{n}", level=level)


def test_required_skills_are_the_strong_ones_and_the_rest_are_preferred() -> None:
    data = career(
        skills=[
            skill(1, "expert"),
            skill(2, "beginner"),
            skill(3, "advanced"),
            skill(4),
            skill(5, "intermediate"),
        ]
    )

    draft = derive_draft(data, TODAY)

    assert draft.required_skills == ["Skill1", "Skill3"]
    assert draft.preferred_skills == ["Skill2", "Skill4", "Skill5"]


def test_at_most_eight_skills_are_required() -> None:
    draft = derive_draft(career(skills=[skill(n, "expert") for n in range(1, 13)]), TODAY)

    assert len(draft.required_skills) == 8
    assert draft.preferred_skills == [f"Skill{n}" for n in range(9, 13)]


def test_without_strong_ratings_the_first_five_unrated_or_middling_skills_are_required() -> None:
    data = career(skills=[skill(1, "beginner"), *[skill(n) for n in range(2, 10)]])

    draft = derive_draft(data, TODAY)

    assert draft.required_skills == ["Skill2", "Skill3", "Skill4", "Skill5", "Skill6"]
    assert "Skill1" in draft.preferred_skills


def test_seniority_and_location_come_from_the_dates_and_the_city() -> None:
    data = career(
        personal=schemas.PersonalWrite(city="Berlin", country="DE"),
        experience=[job("2020-01", "2024-12", title="Engineer")],
    )

    draft = derive_draft(data, TODAY)

    assert draft.years_of_experience == 5.0
    assert draft.seniorities == ["senior"]
    assert draft.locations == ["Berlin"]


def test_no_city_and_no_dates_leave_those_empty() -> None:
    draft = derive_draft(career(skills=[skill(1)]), TODAY)

    assert (draft.seniorities, draft.locations, draft.years_of_experience) == ([], [], None)


def test_the_draft_uses_only_what_matching_uses() -> None:
    assert set(schemas.MatchingDraftOut.model_fields) == {
        "desired_titles",
        "required_skills",
        "preferred_skills",
        "seniorities",
        "locations",
        "years_of_experience",
    }
