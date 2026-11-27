"""Propose a matching profile from a career profile. Nothing is saved or created.

Only what matching uses is read: job titles, skills, the length of the person's experience and
their city. The rules are fixed and visible, with no model involved:

- Roles: the titles of up to three most recent jobs (a current job counts as the latest), with
  repeats removed; the headline when there are no jobs.
- Required skills (a hard filter, so few): the skills rated advanced or expert, at most eight; when
  none is rated that high, the first five that are not rated beginner. Every other skill is a
  preferred skill.
- Seniority from the years worked (`years_of_experience`): under two years junior, under five mid,
  otherwise senior. "Lead" is never derived: it describes a role, which dates cannot show.
- Locations: the city.
"""

from datetime import date

from sanket.career import schemas
from sanket.career.completeness import years_of_experience
from sanket.career.store import CareerData
from sanket.profiles import criteria as limits

MAX_DERIVED_TITLES = 3
MAX_DERIVED_REQUIRED_SKILLS = 8
UNRATED_REQUIRED_SKILLS = 5
JUNIOR_BELOW_YEARS = 2
MID_BELOW_YEARS = 5
STRONG_LEVELS = ("advanced", "expert")
_LATEST = date.max


class NothingToDeriveError(Exception):
    """The career profile has neither a job nor a skill to build a matching profile from."""


def seniorities_for(years: float | None) -> list[str]:
    if years is None:
        return []
    if years < JUNIOR_BELOW_YEARS:
        return ["junior"]
    if years < MID_BELOW_YEARS:
        return ["mid"]
    return ["senior"]


def _titles(data: CareerData) -> list[str]:
    recent_first = sorted(
        data.experience,
        key=lambda job: (_LATEST if job.current or job.end is None else job.end, job.start),
        reverse=True,
    )
    titles: dict[str, str] = {}
    for job in recent_first:
        title = job.title[: limits.MAX_TITLE_CHARS].strip()
        titles.setdefault(title.casefold(), title)
    chosen = list(titles.values())[:MAX_DERIVED_TITLES]
    if not chosen and data.personal.headline:
        chosen = [data.personal.headline[: limits.MAX_TITLE_CHARS].strip()]
    return chosen


def _skills(skills: list[schemas.SkillOut]) -> tuple[list[str], list[str]]:
    strong = [skill for skill in skills if skill.level in STRONG_LEVELS]
    if strong:
        required = strong[:MAX_DERIVED_REQUIRED_SKILLS]
    else:
        required = [skill for skill in skills if skill.level != "beginner"][
            :UNRATED_REQUIRED_SKILLS
        ]
    chosen = {skill.id for skill in required}
    preferred = [skill.name for skill in skills if skill.id not in chosen]
    return [skill.name for skill in required], preferred[: limits.MAX_PREFERRED_SKILLS]


def derive_draft(data: CareerData, today: date | None = None) -> schemas.MatchingDraftOut:
    """The proposed matching profile. Raises `NothingToDeriveError` when there is nothing to use."""
    titles = _titles(data)
    required, preferred = _skills(data.skills)
    if not titles and not required and not preferred:
        raise NothingToDeriveError
    years = years_of_experience(data.experience, today)
    city = data.personal.city[: limits.MAX_LOCATION_CHARS].strip()
    return schemas.MatchingDraftOut(
        desired_titles=titles,
        required_skills=required,
        preferred_skills=preferred,
        seniorities=seniorities_for(years),  # type: ignore[arg-type]
        locations=[city] if city else [],
        years_of_experience=years,
    )
