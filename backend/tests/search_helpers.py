"""Seed searchable jobs for the search tests: a job, its posting, extraction and dates."""

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, update

from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.service import index_pending
from sanket.models import Posting
from tests.factories import add_extraction
from tests.index_helpers import CFG, SPEC, add_indexable_job, representative_posting_id


def extraction_data(**overrides: Any) -> dict[str, Any]:
    """A valid extraction document with the given fields replaced."""
    data: dict[str, Any] = {
        "title": "Backend Engineer",
        "company": "Acme",
        "skills": ["Python", "PostgreSQL"],
        "seniority": "senior",
        "min_years_experience": 3,
        "work_mode": "remote",
        "employment_type": "full_time",
        "country": "DE",
        "city": "Berlin",
        "salary": None,
    }
    data.update(overrides)
    return data


def add_search_job(
    engine: Engine,
    *,
    title: str = "Backend Engineer",
    company: str = "Acme",
    location: str | None = "Berlin",
    description: str | None = "<p>Build APIs.</p>",
    source: str = "greenhouse",
    extraction: dict[str, Any] | None = None,
    published_at: datetime | None = None,
    url: str | None = None,
    posting_count: int = 1,
) -> int:
    """A job whose representative posting has the given source, URL, date and extraction."""
    job_id = add_indexable_job(
        engine,
        title=title,
        company=company,
        location=location,
        description=description,
        source=source,
        posting_count=posting_count,
    )
    posting_id = representative_posting_id(engine, job_id)
    values: dict[str, Any] = {}
    if published_at is not None:
        values["published_at"] = published_at
    if url is not None:
        values["url"] = url
    if values:
        with engine.begin() as conn:
            conn.execute(update(Posting).where(Posting.id == posting_id).values(**values))
    if extraction is not None:
        add_extraction(engine, posting_id, data=extraction)
    return job_id


def index_everything(engine: Engine) -> FakeEmbeddingClient:
    """Index every job with the fake client and return the client (it embeds queries too)."""
    client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    index_pending(CFG, client, apply=True, db_engine=engine)
    return client
