"""Request and response models of the search endpoint."""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sanket.extraction.schema import EmploymentType, Seniority, WorkMode
from sanket.indexing.filters import SearchFilters
from sanket.search.attribution import source_info
from sanket.search.service import SearchHit, SearchPage

MAX_QUERY_CHARS = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
# Matches the largest SEARCH_CANDIDATES the settings allow: no page can start deeper.
MAX_OFFSET = 1000
MAX_FILTER_VALUES = 10
MAX_FILTER_TEXT_CHARS = 200
MAX_SKILL_CHARS = 60
SOURCE_PATTERN = re.compile(r"^[a-z0-9_]{1,50}$")
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")

MatchedBy = Literal["text", "vector", "both"]


def _clean(value: str) -> str:
    # PostgreSQL text cannot hold a NUL character; refuse it here rather than fail in the driver.
    if "\x00" in value:
        raise ValueError("must not contain a NUL character")
    return value.strip()


class SearchParams(BaseModel):
    """Query parameters of `GET /search`. Repeat a parameter to give several values."""

    model_config = ConfigDict(extra="forbid")

    q: str = Field(
        min_length=1,
        max_length=MAX_QUERY_CHARS,
        description='Search text, 1 to 200 characters after trimming. Supports quoted "phrases", '
        "`or` and a leading `-` to exclude a word.",
        examples=["python backend engineer"],
    )
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size.")
    offset: int = Field(
        0,
        ge=0,
        le=MAX_OFFSET,
        description="Results to skip. Results exist only within the first SEARCH_CANDIDATES "
        "ranks; a larger offset returns an empty page.",
    )
    work_mode: list[WorkMode] = Field(default_factory=list, max_length=MAX_FILTER_VALUES)
    seniority: list[Seniority] = Field(default_factory=list, max_length=MAX_FILTER_VALUES)
    employment_type: list[EmploymentType] = Field(
        default_factory=list, max_length=MAX_FILTER_VALUES
    )
    country: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILTER_VALUES,
        description="ISO 3166-1 alpha-2 country codes of the job, from the extraction.",
    )
    source: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILTER_VALUES,
        description="Source identifiers such as `remoteok`; a job matches if any of its "
        "postings comes from one of them.",
    )
    company: str | None = Field(
        None, max_length=MAX_FILTER_TEXT_CHARS, description="Exact company name, ignoring case."
    )
    location: str | None = Field(
        None,
        max_length=MAX_FILTER_TEXT_CHARS,
        description="Text contained in the location, ignoring case. `%` and `_` match themselves.",
    )
    posted_after: datetime | None = Field(
        None,
        description="Only jobs posted at or after this date or time (a date means 00:00 UTC; "
        "a time without a zone is UTC).",
    )
    skills: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILTER_VALUES,
        description="Skills the job must all list (ignoring case), from the extraction.",
    )

    @field_validator("q", "company", "location", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) else value

    @field_validator("company", "location")
    @classmethod
    def _blank_is_no_filter(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("country", mode="before")
    @classmethod
    def _countries(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        codes = [_clean(code).upper() if isinstance(code, str) else code for code in value]
        for code in codes:
            if not isinstance(code, str) or not COUNTRY_PATTERN.match(code):
                raise ValueError("must be an ISO 3166-1 alpha-2 code such as DE")
        return codes

    @field_validator("source")
    @classmethod
    def _sources(cls, value: list[str]) -> list[str]:
        for source in value:
            if not SOURCE_PATTERN.match(source):
                raise ValueError("must be a source identifier such as remoteok")
        return value

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        skills = [_clean(skill) if isinstance(skill, str) else skill for skill in value]
        for skill in skills:
            if not isinstance(skill, str) or not 1 <= len(skill) <= MAX_SKILL_CHARS:
                raise ValueError(f"each skill must be 1 to {MAX_SKILL_CHARS} characters")
        return skills

    @field_validator("posted_after")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def to_filters(self) -> SearchFilters:
        return SearchFilters(
            work_modes=tuple(mode.value for mode in self.work_mode),
            seniorities=tuple(level.value for level in self.seniority),
            employment_types=tuple(kind.value for kind in self.employment_type),
            countries=tuple(self.country),
            sources=tuple(self.source),
            company=self.company,
            location=self.location,
            posted_after=self.posted_after,
            skills=tuple(self.skills),
        )


class SalaryOut(BaseModel):
    """Salary as extracted from the posting text; not converted or normalised."""

    min_amount: float | None = None
    max_amount: float | None = None
    currency: str | None = None
    period: str | None = Field(
        None, description="hour, day, week, month or year; null if unstated."
    )


class ExtractedOut(BaseModel):
    work_mode: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    country: str | None = None
    city: str | None = None
    skills: list[str] = Field(default_factory=list)
    min_years_experience: int | None = None
    salary: SalaryOut | None = None


class SourceOut(BaseModel):
    source: str = Field(description="Source identifier, as used by the `source` filter.")
    name: str = Field(description="Display name of the source.")


class SearchItem(BaseModel):
    job_id: int
    title: str
    company: str
    location: str | None
    source: str | None = Field(description="Source of the posting that `url` points to.")
    source_name: str | None
    url: str | None = Field(description="Link to the original listing. Always link to it.")
    attribution: str | None = Field(
        description="Credit line the source asks to be shown next to the job, if any."
    )
    sources: list[SourceOut] = Field(description="Every source that currently lists the job.")
    published_at: datetime | None
    first_seen_at: datetime
    salary_text: str | None = Field(description="The salary text of the posting, as published.")
    extracted: ExtractedOut | None = Field(
        description="Fields extracted from the posting, null when there is no extraction."
    )
    score: float = Field(
        description="Fused rank score. Orders results within one response; not comparable "
        "between queries."
    )
    matched_by: MatchedBy


EXAMPLE_ITEM: dict[str, Any] = {
    "job_id": 42,
    "title": "Senior Backend Engineer",
    "company": "Acme",
    "location": "Berlin, Germany",
    "source": "remoteok",
    "source_name": "Remote OK",
    "url": "https://remoteok.com/remote-jobs/123",
    "attribution": "Job listing from Remote OK",
    "sources": [{"source": "remoteok", "name": "Remote OK"}],
    "published_at": "2026-11-01T09:00:00Z",
    "first_seen_at": "2026-11-01T10:00:00Z",
    "salary_text": None,
    "extracted": {
        "work_mode": "remote",
        "seniority": "senior",
        "employment_type": "full_time",
        "country": "DE",
        "city": "Berlin",
        "skills": ["Python", "PostgreSQL"],
        "min_years_experience": 5,
        "salary": None,
    },
    "score": 0.0325,
    "matched_by": "both",
}


class SearchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "python backend",
                    "limit": 20,
                    "offset": 0,
                    "total_candidates": 1,
                    "has_more": False,
                    "degraded": False,
                    "degraded_reason": None,
                    "items": [EXAMPLE_ITEM],
                }
            ]
        }
    )

    query: str
    limit: int
    offset: int
    total_candidates: int = Field(
        description="Results available for this query, at most SEARCH_CANDIDATES."
    )
    has_more: bool = Field(description="True when a later page has results.")
    degraded: bool = Field(
        description="True when only full-text results were used because the query could not "
        "be embedded."
    )
    degraded_reason: str | None = Field(
        description="`embeddings_disabled` or `embedding_failed` when degraded."
    )
    items: list[SearchItem]


def _salary(data: Any) -> SalaryOut | None:
    if not isinstance(data, dict):
        return None
    return SalaryOut(
        min_amount=data.get("min_amount"),
        max_amount=data.get("max_amount"),
        currency=data.get("currency"),
        period=data.get("period"),
    )


def _text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _extracted(data: dict[str, Any] | None) -> ExtractedOut | None:
    if not data:
        return None
    skills = data.get("skills")
    years = data.get("min_years_experience")
    return ExtractedOut(
        work_mode=_text(data, "work_mode"),
        seniority=_text(data, "seniority"),
        employment_type=_text(data, "employment_type"),
        country=_text(data, "country"),
        city=_text(data, "city"),
        skills=[s for s in skills if isinstance(s, str)] if isinstance(skills, list) else [],
        min_years_experience=years if isinstance(years, int) else None,
        salary=_salary(data.get("salary")),
    )


def item_from_hit(hit: SearchHit) -> SearchItem:
    details = hit.details
    info = source_info(details.source) if details.source else None
    return SearchItem(
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
        extracted=_extracted(details.extraction),
        score=hit.score,
        matched_by=hit.matched_by,  # type: ignore[arg-type]
    )


def response_from_page(page: SearchPage) -> SearchResponse:
    return SearchResponse(
        query=page.query,
        limit=page.limit,
        offset=page.offset,
        total_candidates=page.total_candidates,
        has_more=page.has_more,
        degraded=page.degraded,
        degraded_reason=page.degraded_reason,
        items=[item_from_hit(hit) for hit in page.hits],
    )
