import pytest
from pydantic import ValidationError

from sanket.extraction.schema import JobExtraction, WorkMode


def valid_data() -> dict:
    return {
        "skills": ["Python", "PostgreSQL"],
        "seniority": "senior",
        "years_experience_min": 3,
        "work_mode": "remote",
        "employment_type": "full_time",
        "education_level": None,
        "salary_min": 50000,
        "salary_max": 80000,
        "salary_currency": "USD",
        "benefits": [],
        "allowed_regions": None,
    }


def test_valid_data_passes() -> None:
    result = JobExtraction.model_validate(valid_data())

    assert result.work_mode == WorkMode.REMOTE
    assert result.skills == ["Python", "PostgreSQL"]


def test_invalid_work_mode_is_rejected() -> None:
    data = valid_data()
    data["work_mode"] = "work from home"

    with pytest.raises(ValidationError):
        JobExtraction.model_validate(data)
