"""The career profile as the API reads and writes it.

A `*Write` model is what a client sends, with every bound checked and unknown fields refused; the
matching `*Out` model adds the row id. Optional text is an empty string, never null. A rule that
involves two fields (an end month after the start month) is raised on the later field, so a client
can show it next to that field.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from sanket.career.fields import (
    MIN_YEAR,
    Month,
    clean_block,
    clean_country,
    clean_line,
    clean_url,
    this_month,
)

Availability = Literal["immediately", "within_one_month", "open_to_offers", "not_looking"]
SkillLevel = Literal["beginner", "intermediate", "advanced", "expert"]
Proficiency = Literal["basic", "conversational", "fluent", "native"]

MAX_FULL_NAME_CHARS = 100
MAX_HEADLINE_CHARS = 120
MAX_SUMMARY_CHARS = 1000
MAX_CITY_CHARS = 100
MAX_INSTITUTION_CHARS = 150
MAX_DEGREE_CHARS = 100
MAX_FIELD_CHARS = 100
MAX_GRADE_CHARS = 50
MAX_COMPANY_CHARS = 150
MAX_JOB_TITLE_CHARS = 150
MAX_JOB_DESCRIPTION_CHARS = 2000
MAX_SKILL_CHARS = 60
MAX_LANGUAGE_CHARS = 60
MAX_CERTIFICATION_CHARS = 150
MAX_ISSUER_CHARS = 100
MAX_PROJECT_CHARS = 150
MAX_PROJECT_DESCRIPTION_CHARS = 1000

MAX_EDUCATION = 10
MAX_EXPERIENCE = 30
MAX_SKILLS = 60
MAX_LANGUAGES = 15
MAX_CERTIFICATIONS = 30
MAX_PROJECTS = 30
# An expected graduation may lie ahead, but not by decades.
MAX_YEARS_AHEAD_FOR_STUDIES = 8

# Single-line text (whitespace collapsed) and multi-line text (line breaks kept), each bounded.
FullName = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_FULL_NAME_CHARS)]
Headline = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_HEADLINE_CHARS)]
Summary = Annotated[str, BeforeValidator(clean_block), Field(max_length=MAX_SUMMARY_CHARS)]
City = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_CITY_CHARS)]
Institution = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_INSTITUTION_CHARS)
]
Degree = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_DEGREE_CHARS)]
StudyField = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_FIELD_CHARS)]
Grade = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_GRADE_CHARS)]
Company = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_COMPANY_CHARS)
]
JobTitle = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_JOB_TITLE_CHARS)
]
JobDescription = Annotated[
    str, BeforeValidator(clean_block), Field(max_length=MAX_JOB_DESCRIPTION_CHARS)
]
SkillName = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_SKILL_CHARS)
]
LanguageName = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_LANGUAGE_CHARS)
]
CertificationTitle = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_CERTIFICATION_CHARS)
]
Issuer = Annotated[str, BeforeValidator(clean_line), Field(max_length=MAX_ISSUER_CHARS)]
ProjectTitle = Annotated[
    str, BeforeValidator(clean_line), Field(min_length=1, max_length=MAX_PROJECT_CHARS)
]
ProjectDescription = Annotated[
    str, BeforeValidator(clean_block), Field(max_length=MAX_PROJECT_DESCRIPTION_CHARS)
]
Country = Annotated[str, BeforeValidator(clean_country)]
GithubUrl = Annotated[str, clean_url("github.com")]
LinkedinUrl = Annotated[str, clean_url("linkedin.com")]
AnyUrl = Annotated[str, clean_url()]


def _not_after_now(value: date, what: str) -> date:
    if value > this_month():
        raise ValueError(f"{what} cannot be in the future")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- personal ---------------------------------------------------------------------------------


class PersonalWrite(_Strict):
    full_name: FullName = ""
    headline: Headline = ""
    summary: Summary = ""
    country: Country = Field(default="", description="ISO 3166-1 alpha-2 code, or empty.")
    city: City = ""
    github_url: GithubUrl = ""
    linkedin_url: LinkedinUrl = ""
    portfolio_url: AnyUrl = ""
    availability: Availability | None = None


# --- education --------------------------------------------------------------------------------


class EducationWrite(_Strict):
    institution: Institution
    degree: Degree = ""
    field: StudyField = ""
    start: Month
    end: Month | None = None
    grade: Grade = ""

    @field_validator("start")
    @classmethod
    def _start(cls, value: date) -> date:
        return _not_after_now(value, "the start month")

    @field_validator("end")
    @classmethod
    def _end(cls, value: date | None, info: ValidationInfo) -> date | None:
        if value is None:
            return None
        start = info.data.get("start")
        if start is not None and value < start:
            raise ValueError("the end month cannot be before the start month")
        latest = this_month().replace(year=this_month().year + MAX_YEARS_AHEAD_FOR_STUDIES)
        if value > latest:
            raise ValueError("the end month is too far ahead")
        return value


class EducationOut(EducationWrite):
    id: int


# --- experience -------------------------------------------------------------------------------


class ExperienceWrite(_Strict):
    company: Company
    title: JobTitle
    start: Month
    current: bool = False
    end: Month | None = Field(default=None, validate_default=True)
    description: JobDescription = ""

    @field_validator("start")
    @classmethod
    def _start(cls, value: date) -> date:
        return _not_after_now(value, "the start month")

    @field_validator("end")
    @classmethod
    def _end(cls, value: date | None, info: ValidationInfo) -> date | None:
        if info.data.get("current"):
            if value is not None:
                raise ValueError("leave the end month empty while you still work here")
            return None
        if value is None:
            raise ValueError("enter the end month, or mark that you still work here")
        _not_after_now(value, "the end month")
        start = info.data.get("start")
        if start is not None and value < start:
            raise ValueError("the end month cannot be before the start month")
        return value


class ExperienceOut(ExperienceWrite):
    id: int


# --- skills and languages ---------------------------------------------------------------------


class SkillWrite(_Strict):
    name: SkillName
    level: SkillLevel | None = None


class SkillOut(SkillWrite):
    id: int


class LanguageWrite(_Strict):
    name: LanguageName
    proficiency: Proficiency


class LanguageOut(LanguageWrite):
    id: int


# --- certifications and projects --------------------------------------------------------------


class CertificationWrite(_Strict):
    title: CertificationTitle
    issuer: Issuer = ""
    year: int | None = Field(default=None, ge=MIN_YEAR)
    url: AnyUrl = ""

    @field_validator("year")
    @classmethod
    def _year(cls, value: int | None) -> int | None:
        if value is not None and value > this_month().year + 1:
            raise ValueError("the year is too far ahead")
        return value


class CertificationOut(CertificationWrite):
    id: int


class ProjectWrite(_Strict):
    title: ProjectTitle
    description: ProjectDescription = ""
    url: AnyUrl = ""


class ProjectOut(ProjectWrite):
    id: int


# --- replacing a whole section ----------------------------------------------------------------


def _no_repeats(names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name.casefold() in seen:
            raise ValueError(f"{what} {name!r} is listed twice")
        seen.add(name.casefold())


class EducationItems(_Strict):
    items: list[EducationWrite] = Field(max_length=MAX_EDUCATION)


class ExperienceItems(_Strict):
    items: list[ExperienceWrite] = Field(max_length=MAX_EXPERIENCE)


class SkillItems(_Strict):
    items: list[SkillWrite] = Field(max_length=MAX_SKILLS)

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[SkillWrite]) -> list[SkillWrite]:
        _no_repeats([item.name for item in items], "the skill")
        return items


class LanguageItems(_Strict):
    items: list[LanguageWrite] = Field(max_length=MAX_LANGUAGES)

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[LanguageWrite]) -> list[LanguageWrite]:
        _no_repeats([item.name for item in items], "the language")
        return items


class CertificationItems(_Strict):
    items: list[CertificationWrite] = Field(max_length=MAX_CERTIFICATIONS)


class ProjectItems(_Strict):
    items: list[ProjectWrite] = Field(max_length=MAX_PROJECTS)


# --- what is read -----------------------------------------------------------------------------


class CompletenessOut(BaseModel):
    percent: int = Field(ge=0, le=100)
    sections: dict[str, bool]
    missing: list[str]


class CareerOut(BaseModel):
    personal: PersonalWrite
    education: list[EducationOut]
    experience: list[ExperienceOut]
    skills: list[SkillOut]
    languages: list[LanguageOut]
    certifications: list[CertificationOut]
    projects: list[ProjectOut]
    completeness: CompletenessOut
    years_of_experience: float | None


class MatchingDraftOut(BaseModel):
    desired_titles: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    seniorities: list[Literal["junior", "mid", "senior"]]
    locations: list[str]
    years_of_experience: float | None
