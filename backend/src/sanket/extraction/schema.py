from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"


class EducationLevel(StrEnum):
    NONE = "none"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"


class JobExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    skills: list[str]
    seniority: Seniority | None
    years_experience_min: int | None
    work_mode: WorkMode | None
    employment_type: EmploymentType | None
    education_level: EducationLevel | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    benefits: list[str]
    allowed_regions: list[str] | None
