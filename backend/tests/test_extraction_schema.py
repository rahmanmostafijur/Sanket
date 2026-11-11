import pytest
from pydantic import ValidationError

from sanket.extraction.schema import JobExtraction, WorkMode


def valid_data() -> dict:
    return {
        "title": "Backend Engineer",
        "company": "Acme",
        "skills": ["Python", "PostgreSQL"],
        "seniority": "senior",
        "min_years_experience": 3,
        "work_mode": "remote",
        "employment_type": "full_time",
        "country": "DE",
        "city": "Berlin",
        "salary": {
            "min_amount": 50000,
            "max_amount": 80000,
            "currency": "USD",
            "period": "year",
        },
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
