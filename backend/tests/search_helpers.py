"""Seed searchable jobs for the search tests: a job, its posting, extraction and dates."""

import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, update

from sanket.api import create_app
from sanket.config import Settings
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
    fingerprint: str | None = None,
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
        fingerprint=fingerprint,
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


def index_everything(engine: Engine, excluded_sources: tuple[str, ...] = ()) -> FakeEmbeddingClient:
    """Index every job with the fake client and return the client (it embeds queries too).

    Jobs from `excluded_sources` get a full-text entry but no embedding.
    """
    client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    cfg = replace(CFG, excluded_sources=excluded_sources)
    index_pending(cfg, client, apply=True, db_engine=engine)
    return client


def seed_filter_corpus(engine: Engine) -> dict[str, int]:
    jobs = {
        "remote_senior": add_search_job(
            engine,
            title="Senior Engineer",
            company="Acme",
            location="Berlin, Germany",
            extraction=extraction_data(skills=["Python", "Go"]),
            published_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
        "hybrid_junior": add_search_job(
            engine,
            title="Junior Engineer",
            company="Zeta Corp",
            location="Stockholm, Sweden",
            source="lever",
            extraction=extraction_data(
                seniority="junior",
                work_mode="hybrid",
                employment_type="part_time",
                country="SE",
                skills=["python", "Rust"],
            ),
            published_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        "onsite_lead": add_search_job(
            engine,
            title="Lead Engineer",
            company="100% Bakers_Inc",
            location="Dhaka, Bangladesh",
            source="remoteok",
            extraction=extraction_data(
                seniority="lead",
                work_mode="onsite",
                employment_type="contract",
                country="BD",
                skills=["Java"],
            ),
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
        "no_extraction": add_search_job(
            engine, title="Engineer Unknown", company="Mystery", location=None
        ),
    }
    return jobs


def api_client(
    engine: Engine, embedding_client: FakeEmbeddingClient | None, **settings: Any
) -> TestClient:
    """A test client for the app, wired to the test database and the given embedding client."""
    config = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        embedding_model=SPEC.model_name,
        embedding_model_version=SPEC.model_version,
        embedding_dimensions=SPEC.dimensions,
        **{"auth_dev_bypass": True, **settings},
    )
    return TestClient(create_app(config, engine, embedding_client))
