"""Validated structure extracted from one job posting."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_extra_types.country import CountryAlpha2
from pydantic_extra_types.currency_code import ISO4217

# Bump when fields, enums or validation rules change; stored with every extraction.
SCHEMA_VERSION = 2

MAX_SKILLS = 30
MAX_SKILL_LENGTH = 60
MAX_NAME_LENGTH = 200
MAX_YEARS_EXPERIENCE = 50


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def normalise_skills(skills: list[str]) -> list[str]:
    """Collapse whitespace, drop empty or overlong entries, dedupe ignoring case, cap at 30."""
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        name = " ".join(skill.split())
        key = name.casefold()
        if not name or len(name) > MAX_SKILL_LENGTH or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result[:MAX_SKILLS]


class Salary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_amount: float | None = Field(default=None, ge=0, description="Lowest stated amount.")
    max_amount: float | None = Field(default=None, ge=0, description="Highest stated amount.")
    currency: ISO4217 = Field(description="ISO 4217 currency code, for example USD.")
    period: SalaryPeriod | None = Field(default=None, description="Null if not stated.")

    @model_validator(mode="after")
    def _check_range(self) -> "Salary":
        if self.min_amount is None and self.max_amount is None:
            raise ValueError("at least one of min_amount and max_amount is required")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must not be greater than max_amount")
        return self


class JobExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    company: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    seniority: Seniority
    work_mode: WorkMode
    employment_type: EmploymentType
    country: CountryAlpha2 | None = Field(
        default=None, description="ISO 3166-1 alpha-2 code of the single job country, or null."
    )
    city: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    skills: list[str] = Field(
        default_factory=list, description=f"At most {MAX_SKILLS} distinct skills."
    )
    min_years_experience: int | None = Field(default=None, ge=0, le=MAX_YEARS_EXPERIENCE)
    salary: Salary | None = None

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("company", "city")
    @classmethod
    def _clean_names(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("skills")
    @classmethod
    def _normalise_skills(cls, value: list[str]) -> list[str]:
        return normalise_skills(value)
