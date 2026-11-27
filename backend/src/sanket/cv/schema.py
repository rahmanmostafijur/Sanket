"""What is read from a CV: personal info and the fields of a profile.

This is both the schema the language model must answer with and the proposal returned to the
client, so it mirrors the profile form. Every field may be empty, because a CV does not say
everything and a missing value must stay missing. The validators only clean and bound: text is
collapsed, lists are de-duplicated and cut to the profile's own limits, `unknown` and invalid
codes are dropped instead of failing the whole answer, and required skills are held to the few
that are central (the rest move to preferred skills), whatever the model answered.
"""

from typing import Any

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sanket.accounts.personal import (
    MAX_FULL_NAME_CHARS,
    MAX_HEADLINE_CHARS,
    MAX_LOCATION_CHARS,
    MAX_PERSONAL_SUMMARY_CHARS,
)
from sanket.extraction.schema import EmploymentType, Seniority, WorkMode
from sanket.profiles import criteria as limits

# Required skills are a hard filter on matching, so only a handful that define the person.
MAX_PROPOSED_REQUIRED_SKILLS = 8
# Bumped when the fields or the rules change.
CV_SCHEMA_VERSION = 1


def _text(value: Any, max_chars: int) -> Any:
    """Whitespace collapsed and cut to `max_chars`; anything but text is left to validation."""
    if not isinstance(value, str):
        return value
    return limits.clean_text(value.replace("\x00", ""))[:max_chars].rstrip()


def _entries(values: Any, max_chars: int, max_items: int) -> Any:
    """Cleaned, de-duplicated entries, dropping those that are too long, up to `max_items`."""
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        return values
    cleaned = limits.clean_list([v.replace("\x00", "") for v in values])
    return [v for v in cleaned if len(v) <= max_chars][:max_items]


class CvPersonal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(default="", description="The person's name as written, or empty.")
    headline: str = Field(
        default="", description="A short professional headline the CV states, or empty."
    )
    location: str = Field(default="", description="Where the CV says the person is based.")
    summary: str = Field(
        default="", description="A short factual summary of the person's background, or empty."
    )

    @field_validator("full_name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> Any:
        return _text(value, MAX_FULL_NAME_CHARS)

    @field_validator("headline", mode="before")
    @classmethod
    def _headline(cls, value: Any) -> Any:
        return _text(value, MAX_HEADLINE_CHARS)

    @field_validator("location", mode="before")
    @classmethod
    def _location(cls, value: Any) -> Any:
        return _text(value, MAX_LOCATION_CHARS)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: Any) -> Any:
        return _text(value, MAX_PERSONAL_SUMMARY_CHARS)


def _known(values: list[Any], unknown: str) -> list[Any]:
    """The values without `unknown` and without repeats, in order."""
    return list(dict.fromkeys(v for v in values if getattr(v, "value", v) != unknown))


class CvProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desired_titles: list[str] = Field(
        default_factory=list,
        description="Roles the CV says the person is after, else their current or latest role.",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description=f"At most {MAX_PROPOSED_REQUIRED_SKILLS} skills clearly central to the CV.",
    )
    preferred_skills: list[str] = Field(
        default_factory=list, description="Every other skill, tool or technology the CV lists."
    )
    seniorities: list[Seniority] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    employment_types: list[EmploymentType] = Field(default_factory=list)
    countries: list[str] = Field(
        default_factory=list,
        description="ISO 3166-1 alpha-2 codes of countries the CV says the person wants.",
    )
    locations: list[str] = Field(
        default_factory=list, description="Places the CV says the person wants to work."
    )
    summary: str = Field(
        default="", description="What the person is looking for, only if the CV states it."
    )

    @field_validator("desired_titles", mode="before")
    @classmethod
    def _titles(cls, value: Any) -> Any:
        return _entries(value, limits.MAX_TITLE_CHARS, limits.MAX_TITLES)

    @field_validator("required_skills", "preferred_skills", mode="before")
    @classmethod
    def _skills(cls, value: Any) -> Any:
        return _entries(value, limits.MAX_SKILL_CHARS, 3 * limits.MAX_PREFERRED_SKILLS)

    @field_validator("locations", mode="before")
    @classmethod
    def _locations(cls, value: Any) -> Any:
        return _entries(value, limits.MAX_LOCATION_CHARS, limits.MAX_LOCATIONS)

    @field_validator("summary", mode="before")
    @classmethod
    def _looking_for(cls, value: Any) -> Any:
        return _text(value, limits.MAX_SUMMARY_CHARS)

    @field_validator("seniorities", mode="after")
    @classmethod
    def _seniorities(cls, value: list[Seniority]) -> list[Seniority]:
        return _known(value, Seniority.UNKNOWN.value)

    @field_validator("work_modes", mode="after")
    @classmethod
    def _work_modes(cls, value: list[WorkMode]) -> list[WorkMode]:
        return _known(value, WorkMode.UNKNOWN.value)

    @field_validator("employment_types", mode="after")
    @classmethod
    def _employment_types(cls, value: list[EmploymentType]) -> list[EmploymentType]:
        return _known(value, EmploymentType.UNKNOWN.value)

    @field_validator("countries", mode="before")
    @classmethod
    def _countries(cls, value: Any) -> Any:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return value
        codes = dict.fromkeys(limits.clean_text(v).upper() for v in value)
        valid = [c for c in codes if len(c) == 2 and pycountry.countries.get(alpha_2=c)]
        return valid[: limits.MAX_COUNTRIES]

    @model_validator(mode="after")
    def _keep_required_skills_central(self) -> "CvProfile":
        """Only the first few required skills stay required; any others become preferred, and
        a skill is never listed twice."""
        required = self.required_skills[:MAX_PROPOSED_REQUIRED_SKILLS]
        demoted = self.required_skills[MAX_PROPOSED_REQUIRED_SKILLS:]
        taken = {skill.casefold() for skill in required}
        preferred = [s for s in [*demoted, *self.preferred_skills] if s.casefold() not in taken]
        self.required_skills = required
        self.preferred_skills = limits.clean_list(preferred)[: limits.MAX_PREFERRED_SKILLS]
        return self


class CvExtraction(BaseModel):
    """The answer of the model, and the proposal sent to the client. Nothing in it is saved."""

    model_config = ConfigDict(extra="forbid")

    personal: CvPersonal = Field(default_factory=CvPersonal)
    profile: CvProfile = Field(default_factory=CvProfile)
