"""Filters for the retrieval queries, applied inside the candidate queries.

A filter narrows the set the full-text and the vector query search, rather than trimming
their top results afterwards, so a restrictive filter cannot leave a page empty just because
the best matches happened to be excluded. Values come from two places:

- the canonical `job` row: company, location, and whether it still has postings;
- the newest successful extraction of the job's representative posting (a JSONB document, see
  `sanket.extraction.schema`): work mode, seniority, employment type, country and skills.
  A job without a successful extraction never matches a filter on those fields.

Everything user supplied is a bound parameter (`icontains(..., autoescape=True)` escapes the
LIKE wildcards of the location filter, so `%` and `_` match themselves).

Salary is filtered only within one currency: the extracted amount (the maximum, else the
minimum) is annualised by its period and compared with an annual minimum given together with
its currency. Amounts are never converted between currencies, and a salary without a period
cannot be annualised, so such jobs never pass a minimum salary filter.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Float, Select, case, cast, exists, func, select, true

from sanket.extraction.runner import STATUS_OK
from sanket.models import Job, JobEmbedding, Posting, PostingExtraction


@dataclass(frozen=True)
class SearchFilters:
    """Empty values mean "no filter". Several values within one field are ORed, except
    `skills`, where every skill must be present (a narrowing requirement)."""

    work_modes: tuple[str, ...] = ()
    seniorities: tuple[str, ...] = ()
    employment_types: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    company: str | None = None
    location: str | None = None
    posted_after: datetime | None = None
    skills: tuple[str, ...] = ()
    # An annual minimum in `salary_currency` (both or neither); see the module docstring.
    salary_min: float | None = None
    salary_currency: str | None = None
    has_salary: bool = False

    @property
    def needs_extraction(self) -> bool:
        return bool(
            self.work_modes
            or self.seniorities
            or self.employment_types
            or self.countries
            or self.skills
            or self.salary_min is not None
            or self.has_salary
        )


# How many of each period make a year (a 40-hour week, 260 working days).
PERIODS_PER_YEAR: dict[str, int] = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}


def latest_extraction_lateral() -> Any:
    """`LATERAL (newest ok extraction of the job's representative posting)` as `extraction`."""
    return (
        select(PostingExtraction.data.label("data"))
        .where(
            PostingExtraction.posting_id == Job.representative_posting_id,
            PostingExtraction.status == STATUS_OK,
        )
        .order_by(PostingExtraction.schema_version.desc(), PostingExtraction.prompt_version.desc())
        .limit(1)
        .lateral("extraction")
    )


def _field_in(extraction: Any, field: str, values: tuple[str, ...]) -> ColumnElement[bool]:
    condition: ColumnElement[bool] = extraction.c.data[field].astext.in_(values)
    return condition


def _has_skill(extraction: Any, skill: str) -> ColumnElement[bool]:
    element = func.jsonb_array_elements_text(extraction.c.data["skills"]).table_valued("value")
    return exists(
        select(1).select_from(element).where(func.lower(element.c.value) == skill.lower())
    )


def _salary_amount(extraction: Any) -> ColumnElement[Any]:
    salary = extraction.c.data["salary"]
    return func.coalesce(
        cast(salary["max_amount"].astext, Float), cast(salary["min_amount"].astext, Float)
    )


def _has_salary(extraction: Any) -> ColumnElement[bool]:
    return _salary_amount(extraction).is_not(None)


def _salary_at_least(extraction: Any, minimum: float, currency: str) -> ColumnElement[bool]:
    salary = extraction.c.data["salary"]
    factor = case(
        *((salary["period"].astext == period, n) for period, n in PERIODS_PER_YEAR.items()),
        else_=None,
    )
    condition: ColumnElement[bool] = (salary["currency"].astext == currency.upper()) & (
        _salary_amount(extraction) * factor >= minimum
    )
    return condition


def _published_at() -> ColumnElement[Any]:
    """When the job was posted: its representative posting's date, else when we first saw it."""
    posted = (
        select(Posting.published_at)
        .where(Posting.id == Job.representative_posting_id)
        .scalar_subquery()
    )
    return func.coalesce(posted, Job.first_seen_at)


def posted_at() -> ColumnElement[Any]:
    """When a job was posted, for ordering: see `_published_at`."""
    return _published_at()


def _any_posting_from(sources: tuple[str, ...]) -> ColumnElement[bool]:
    return exists().where(Posting.job_id == Job.id, Posting.source.in_(sources))


def _conditions(filters: SearchFilters, extraction: Any) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    for field, values in (
        ("work_mode", filters.work_modes),
        ("seniority", filters.seniorities),
        ("employment_type", filters.employment_types),
        ("country", filters.countries),
    ):
        if values:
            conditions.append(_field_in(extraction, field, values))
    conditions.extend(_has_skill(extraction, skill) for skill in filters.skills)
    if filters.has_salary:
        conditions.append(_has_salary(extraction))
    if filters.salary_min is not None and filters.salary_currency:
        conditions.append(_salary_at_least(extraction, filters.salary_min, filters.salary_currency))
    if filters.sources:
        conditions.append(_any_posting_from(filters.sources))
    if filters.company:
        conditions.append(func.lower(Job.company) == filters.company.strip().lower())
    if filters.location:
        conditions.append(Job.location.icontains(filters.location.strip(), autoescape=True))
    if filters.posted_after is not None:
        conditions.append(_published_at() >= filters.posted_after)
    return conditions


def restrict_to_live_jobs(stmt: Select[Any], filters: SearchFilters) -> Select[Any]:
    """Add the filters (and "the job still has postings") to a statement that selects from
    `job`, or from `job_embedding` already joined to `job`."""
    if filters.needs_extraction:
        extraction = latest_extraction_lateral()
        stmt = stmt.join_from(Job, extraction, true(), isouter=True)
    else:
        extraction = None
    return stmt.where(Job.posting_count > 0, *_conditions(filters, extraction))


def join_job(stmt: Select[Any]) -> Select[Any]:
    """Join `job` to a statement that selects from `job_embedding`."""
    return stmt.join_from(JobEmbedding, Job, Job.id == JobEmbedding.job_id)
