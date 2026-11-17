"""The plain data the matcher works on: what is known about a job and a profile, and the score."""

from dataclasses import dataclass, field
from typing import Any

from sanket.profiles.criteria import ProfileCriteria
from sanket.profiles.store import ProfileRow


@dataclass(frozen=True)
class JobView:
    """What scoring needs from a job. Fields the extraction does not know are None."""

    job_id: int
    title: str
    location: str | None
    seniority: str | None
    work_mode: str | None
    employment_type: str | None
    country: str | None
    skills: tuple[str, ...]
    embedding_hash: str


@dataclass(frozen=True)
class ProfileView:
    profile_id: int
    owner_id: str
    content_hash: str
    desired_titles: tuple[str, ...]
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    seniorities: frozenset[str]
    work_modes: frozenset[str]
    employment_types: frozenset[str]
    countries: frozenset[str]
    locations: tuple[str, ...]
    min_score_override: float | None

    @classmethod
    def from_row(cls, row: ProfileRow) -> "ProfileView":
        criteria = ProfileCriteria.model_validate(row.criteria)
        return cls(
            profile_id=row.id,
            owner_id=row.owner_id,
            content_hash=row.content_hash,
            desired_titles=tuple(criteria.desired_titles),
            required_skills=tuple(criteria.required_skills),
            preferred_skills=tuple(criteria.preferred_skills),
            seniorities=frozenset(level.value for level in criteria.seniorities),
            work_modes=frozenset(mode.value for mode in criteria.work_modes),
            employment_types=frozenset(kind.value for kind in criteria.employment_types),
            countries=frozenset(criteria.countries),
            locations=tuple(criteria.locations),
            min_score_override=criteria.min_score_override,
        )


@dataclass(frozen=True)
class MatchScore:
    """The outcome of scoring one job against one profile.

    `score` is the blended score in [0, 1] (computed even when a filter failed, to explain
    why). `passed_filters` says whether every hard filter held; `is_match` also requires the
    minimum cosine similarity and the score threshold.
    """

    score: float
    components: dict[str, Any] = field(default_factory=dict)
    passed_filters: bool = True
    is_match: bool = True
