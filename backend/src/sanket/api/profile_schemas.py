"""Request and response models of the profile endpoints.

Creating and replacing take `ProfileWrite` (`sanket.profiles.criteria`) as it is: a name, the
`active` flag and the criteria, with every bound and `extra="forbid"` on the model itself.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sanket.api.schemas import ExtractedOut, SourceOut, extracted_from
from sanket.extraction.schema import EmploymentType, Seniority, WorkMode
from sanket.matching.matches import MatchItem, MatchPage
from sanket.profiles import criteria as limits
from sanket.profiles.store import ProfileRow
from sanket.search.attribution import source_info

EmbeddingStatusName = Literal["pending", "ready", "failed"]
MAX_MATCH_PAGE = 100
DEFAULT_MATCH_PAGE = 50


class ProfileOut(BaseModel):
    id: int
    name: str
    active: bool
    desired_titles: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    seniorities: list[str]
    work_modes: list[str]
    employment_types: list[str]
    countries: list[str]
    locations: list[str]
    summary: str
    min_score_override: float | None
    embedding_status: EmbeddingStatusName = Field(
        description="`pending` until the profile's current content is embedded, `ready` when "
        "it is being matched, `failed` when the last attempt to embed it failed (it is "
        "retried; saving the profile again also queues it again)."
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: ProfileRow) -> "ProfileOut":
        criteria = row.criteria
        return cls(
            id=row.id,
            name=row.name,
            active=row.active,
            desired_titles=criteria.get("desired_titles", []),
            required_skills=criteria.get("required_skills", []),
            preferred_skills=criteria.get("preferred_skills", []),
            seniorities=criteria.get("seniorities", []),
            work_modes=criteria.get("work_modes", []),
            employment_types=criteria.get("employment_types", []),
            countries=criteria.get("countries", []),
            locations=criteria.get("locations", []),
            summary=criteria.get("summary", ""),
            min_score_override=criteria.get("min_score_override"),
            embedding_status=row.embedding_status,  # type: ignore[arg-type]
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ProfileList(BaseModel):
    items: list[ProfileOut]


class ProfilePatch(BaseModel):
    """Any subset of the profile fields; the result must be a valid profile as a whole."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=limits.MAX_NAME_CHARS)
    active: bool | None = None
    desired_titles: list[limits.Title] | None = Field(default=None, max_length=limits.MAX_TITLES)
    required_skills: list[limits.Skill] | None = Field(
        default=None, max_length=limits.MAX_REQUIRED_SKILLS
    )
    preferred_skills: list[limits.Skill] | None = Field(
        default=None, max_length=limits.MAX_PREFERRED_SKILLS
    )
    seniorities: list[Seniority] | None = Field(default=None, max_length=len(Seniority))
    work_modes: list[WorkMode] | None = Field(default=None, max_length=len(WorkMode))
    employment_types: list[EmploymentType] | None = Field(
        default=None, max_length=len(EmploymentType)
    )
    countries: list[str] | None = Field(default=None, max_length=limits.MAX_COUNTRIES)
    locations: list[limits.Location] | None = Field(default=None, max_length=limits.MAX_LOCATIONS)
    summary: str | None = Field(default=None, max_length=limits.MAX_SUMMARY_CHARS)
    min_score_override: float | None = Field(default=None, ge=0, le=1)

    def changes(self) -> dict[str, Any]:
        """The fields the client sent (an explicit null clears `min_score_override`)."""
        return self.model_dump(exclude_unset=True, mode="json")


class MatchedJob(BaseModel):
    """The job of a match, with the link and credit that must be shown with it."""

    job_id: int
    title: str
    company: str
    location: str | None
    source: str | None
    source_name: str | None
    url: str | None = Field(description="Link to the original listing. Always link to it.")
    attribution: str | None
    sources: list[SourceOut]
    published_at: datetime | None
    first_seen_at: datetime
    salary_text: str | None
    extracted: ExtractedOut | None


class MatchOut(BaseModel):
    id: int = Field(description="Increases with every new match; use it as `after_id`.")
    job_id: int
    score: float = Field(description="0 to 1; see `components` for how it was reached.")
    status: Literal["active", "withdrawn"]
    components: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    job: MatchedJob | None = Field(description="Null if the job no longer exists.")

    @classmethod
    def from_item(cls, item: MatchItem) -> "MatchOut":
        return cls(
            id=item.id,
            job_id=item.job_id,
            score=item.score,
            status=item.status,  # type: ignore[arg-type]
            components=item.components,
            created_at=item.created_at,
            updated_at=item.updated_at,
            job=_matched_job(item),
        )


def _matched_job(item: MatchItem) -> MatchedJob | None:
    details = item.job
    if details is None:
        return None
    info = source_info(details.source) if details.source else None
    return MatchedJob(
        job_id=details.job_id,
        title=details.title,
        company=details.company,
        location=details.location,
        source=details.source,
        source_name=info.name if info else None,
        url=details.url,
        attribution=info.attribution if info else None,
        sources=[SourceOut(source=name, name=source_info(name).name) for name in details.sources],
        published_at=details.published_at,
        first_seen_at=details.first_seen_at,
        salary_text=details.salary_text,
        extracted=extracted_from(details.extraction),
    )


class MatchList(BaseModel):
    items: list[MatchOut]
    next_after_id: int | None = Field(
        description="Pass as `after_id` to continue; null when this page is empty."
    )
    has_more: bool

    @classmethod
    def from_page(cls, page: MatchPage) -> "MatchList":
        return cls(
            items=[MatchOut.from_item(item) for item in page.items],
            next_after_id=page.next_after_id,
            has_more=page.has_more,
        )
