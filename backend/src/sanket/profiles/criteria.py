"""What a profile asks for, validated. Everything here is untrusted input.

Every list and text has a bound, text is stripped and whitespace collapsed, a NUL character
(which PostgreSQL text cannot hold) is refused, list entries are de-duplicated ignoring case
keeping the first spelling, and unknown fields are refused. A profile must say something to
match on: at least one desired title, one skill or a summary.
"""

from typing import Annotated, Any

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sanket.extraction.schema import EmploymentType, Seniority, WorkMode

MAX_NAME_CHARS = 100
MAX_TITLES = 10
MAX_TITLE_CHARS = 100
MAX_REQUIRED_SKILLS = 20
MAX_PREFERRED_SKILLS = 30
MAX_SKILL_CHARS = 60
MAX_LOCATIONS = 10
MAX_LOCATION_CHARS = 100
MAX_COUNTRIES = 20
MAX_SUMMARY_CHARS = 2000

Title = Annotated[str, Field(max_length=MAX_TITLE_CHARS)]
Skill = Annotated[str, Field(max_length=MAX_SKILL_CHARS)]
Location = Annotated[str, Field(max_length=MAX_LOCATION_CHARS)]


def clean_text(value: str) -> str:
    """Whitespace collapsed and trimmed; a NUL character is an error."""
    if "\x00" in value:
        raise ValueError("must not contain a NUL character")
    return " ".join(value.split())


def clean_list(values: list[str]) -> list[str]:
    """Each entry cleaned, empty ones dropped, duplicates (ignoring case) removed."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _without_unknown(values: list[Any], unknown: str) -> list[Any]:
    """Drop duplicates (keeping order) and refuse `unknown`, which is not something to ask for."""
    if any(getattr(value, "value", value) == unknown for value in values):
        raise ValueError("'unknown' is not a value to ask for; leave the list empty instead")
    return list(dict.fromkeys(values))


class ProfileCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desired_titles: list[Title] = Field(default_factory=list, max_length=MAX_TITLES)
    required_skills: list[Skill] = Field(
        default_factory=list,
        max_length=MAX_REQUIRED_SKILLS,
        description="Skills a job must list (see MATCH_REQUIRED_SKILLS_MIN_FRACTION).",
    )
    preferred_skills: list[Skill] = Field(
        default_factory=list,
        max_length=MAX_PREFERRED_SKILLS,
        description="Skills that raise the score.",
    )
    seniorities: list[Seniority] = Field(default_factory=list, max_length=len(Seniority))
    work_modes: list[WorkMode] = Field(default_factory=list, max_length=len(WorkMode))
    employment_types: list[EmploymentType] = Field(
        default_factory=list, max_length=len(EmploymentType)
    )
    countries: list[str] = Field(
        default_factory=list,
        max_length=MAX_COUNTRIES,
        description="ISO 3166-1 alpha-2 codes of the countries wanted.",
    )
    locations: list[Location] = Field(
        default_factory=list,
        max_length=MAX_LOCATIONS,
        description="Free-text places, for the embedding and shown with matches.",
    )
    summary: str = Field(
        default="",
        max_length=MAX_SUMMARY_CHARS,
        description="In your own words, what you are looking for.",
    )
    min_score_override: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Minimum match score for this profile instead of the server default.",
    )

    @field_validator("desired_titles", "required_skills", "preferred_skills", "locations")
    @classmethod
    def _clean_lists(cls, value: list[str]) -> list[str]:
        return clean_list(value)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        return clean_text(value)

    @field_validator("seniorities")
    @classmethod
    def _seniorities(cls, value: list[Seniority]) -> list[Seniority]:
        return _without_unknown(value, Seniority.UNKNOWN.value)

    @field_validator("work_modes")
    @classmethod
    def _work_modes(cls, value: list[WorkMode]) -> list[WorkMode]:
        return _without_unknown(value, WorkMode.UNKNOWN.value)

    @field_validator("employment_types")
    @classmethod
    def _employment_types(cls, value: list[EmploymentType]) -> list[EmploymentType]:
        return _without_unknown(value, EmploymentType.UNKNOWN.value)

    @field_validator("countries")
    @classmethod
    def _countries(cls, value: list[str]) -> list[str]:
        codes = list(dict.fromkeys(clean_text(code).upper() for code in value))
        for code in codes:
            if len(code) != 2 or pycountry.countries.get(alpha_2=code) is None:
                raise ValueError(f"{code!r} is not an ISO 3166-1 alpha-2 country code")
        return codes

    @model_validator(mode="after")
    def _says_something(self) -> "ProfileCriteria":
        if not (
            self.desired_titles or self.required_skills or self.preferred_skills or self.summary
        ):
            raise ValueError("give at least a desired title, a skill or a summary")
        return self


class ProfileWrite(ProfileCriteria):
    """The body of creating or replacing a profile: a name, whether it is active, the criteria."""

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    active: bool = True

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        name = clean_text(value)
        if not name:
            raise ValueError("must not be blank")
        return name


def criteria_of(data: ProfileCriteria) -> ProfileCriteria:
    """Just the criteria of a `ProfileWrite` (a new object; the name and flag are dropped)."""
    return ProfileCriteria.model_validate(
        data.model_dump(include=set(ProfileCriteria.model_fields))
    )
