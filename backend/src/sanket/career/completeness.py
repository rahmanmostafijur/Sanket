"""How complete a career profile is, and how long the person has worked.

Completeness is plain counting: the profile has seven sections and each is either filled or not,
so the percentage is the share of filled sections and the empty ones are named. There are no
scores, levels or badges. A section is filled when it holds an entry; the personal section when
it has a name, a headline, a summary and a country.
"""

from collections.abc import Sequence
from datetime import date

from sanket.career import schemas
from sanket.career.fields import this_month
from sanket.career.store import CareerData

SECTION_NAMES = (
    "personal",
    "education",
    "experience",
    "skills",
    "languages",
    "certifications",
    "projects",
)
MONTHS_PER_YEAR = 12


def personal_is_filled(personal: schemas.PersonalWrite) -> bool:
    return all((personal.full_name, personal.headline, personal.summary, personal.country))


def completeness_of(data: CareerData) -> schemas.CompletenessOut:
    filled = {
        "personal": personal_is_filled(data.personal),
        "education": bool(data.education),
        "experience": bool(data.experience),
        "skills": bool(data.skills),
        "languages": bool(data.languages),
        "certifications": bool(data.certifications),
        "projects": bool(data.projects),
    }
    return schemas.CompletenessOut(
        percent=round(100 * sum(filled.values()) / len(SECTION_NAMES)),
        sections=filled,
        missing=[name for name in SECTION_NAMES if not filled[name]],
    )


def _month_index(day: date) -> int:
    return day.year * MONTHS_PER_YEAR + day.month - 1


def years_of_experience(
    experience: Sequence[schemas.ExperienceOut], today: date | None = None
) -> float | None:
    """Years worked, from the employment dates: the months covered by at least one job, so two
    jobs held at the same time count once. A current job runs to this month. None without any."""
    if not experience:
        return None
    now = _month_index(today or this_month())
    spans = sorted(
        (_month_index(job.start), now if job.current or job.end is None else _month_index(job.end))
        for job in experience
    )
    months = 0
    start, end = spans[0]
    for next_start, next_end in spans[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            months += end - start + 1
            start, end = next_start, next_end
    months += end - start + 1
    return round(months / MONTHS_PER_YEAR, 1)
