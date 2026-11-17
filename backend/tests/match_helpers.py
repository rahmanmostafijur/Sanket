"""Builders for the matching tests: views, configs, profiles saved and embedded in the database."""

import os
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update

from sanket.api import create_app
from sanket.config import Settings
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.service import index_jobs, index_pending
from sanket.matching.config import MatchConfig
from sanket.matching.notify import MatchRecord
from sanket.matching.types import JobView, ProfileView
from sanket.models import EmbeddingStatus, JobMatch, Posting, PostingExtraction, Profile
from sanket.profiles.criteria import ProfileWrite
from sanket.profiles.embedding import embed_profile
from sanket.profiles.service import create_profile
from sanket.profiles.service import get as get_profile_row
from sanket.profiles.store import ProfileRow
from tests.index_helpers import CFG as INDEX_CFG
from tests.index_helpers import SPEC, representative_posting_id
from tests.search_helpers import add_search_job, extraction_data

OWNER = "owner-1"
CFG = MatchConfig(spec=SPEC)


def job_view(**overrides: Any) -> JobView:
    values: dict[str, Any] = {
        "job_id": 1,
        "title": "Senior Backend Engineer",
        "location": "Berlin, Germany",
        "seniority": "senior",
        "work_mode": "remote",
        "employment_type": "full_time",
        "country": "DE",
        "skills": ("Python", "PostgreSQL"),
        "embedding_hash": "job-hash",
    }
    values.update(overrides)
    return JobView(**values)


def profile_view(**overrides: Any) -> ProfileView:
    values: dict[str, Any] = {
        "profile_id": 1,
        "owner_id": OWNER,
        "content_hash": "profile-hash",
        "desired_titles": (),
        "required_skills": (),
        "preferred_skills": (),
        "seniorities": frozenset(),
        "work_modes": frozenset(),
        "employment_types": frozenset(),
        "countries": frozenset(),
        "locations": (),
        "min_score_override": None,
    }
    values.update(overrides)
    return ProfileView(**values)


def config(**overrides: Any) -> MatchConfig:
    return replace(CFG, **overrides)


def profile_body(**overrides: Any) -> ProfileWrite:
    values: dict[str, Any] = {
        "name": "Backend",
        "summary": "backend engineer python apis",
        "desired_titles": ["Backend Engineer"],
    }
    values.update(overrides)
    return ProfileWrite.model_validate(values)


def add_profile(
    engine: Engine, *, owner_id: str = OWNER, embed: bool = True, **overrides: Any
) -> ProfileRow:
    """Save a profile, and with `embed` (the default) embed it with the fake client so it is
    ready to be matched."""
    saved = create_profile(
        owner_id, profile_body(**overrides), queue=None, max_profiles=1000, db_engine=engine
    )
    if not embed:
        return saved.profile
    embed_profile(saved.profile.id, FakeEmbeddingClient(), SPEC, db_engine=engine)
    return get_profile_row(owner_id, saved.profile.id, engine)


def status_of(engine: Engine, profile_id: int) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                select(Profile.embedding_status).where(Profile.id == profile_id)
            ).scalar_one()
        )


READY = EmbeddingStatus.READY


class ScriptedQueryClient(FakeEmbeddingClient):
    """The fake client whose `embed_query` can raise or run a callback first."""

    def __init__(
        self,
        error: Exception | None = None,
        on_query: Callable[[str], None] | None = None,
        dimensions: int = 768,
    ) -> None:
        super().__init__(
            dimensions=dimensions, model_name=SPEC.model_name, model_version=SPEC.model_version
        )
        self.error = error
        self.on_query = on_query

    def embed_query(self, text: str) -> list[float]:
        if self.on_query is not None:
            self.on_query(text)
        if self.error is not None:
            self.query_calls.append(text)
            raise self.error
        return super().embed_query(text)


def profile_client(
    engine: Engine,
    queue: Any = None,
    owner: str = OWNER,
    provider: FakeEmbeddingClient | None = None,
    **settings: Any,
) -> TestClient:
    """A test client acting as `owner`, wired to the test database and the given queue."""
    config = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        embedding_model=SPEC.model_name,
        embedding_model_version=SPEC.model_version,
        embedding_dimensions=SPEC.dimensions,
        default_owner_id=owner,
        **settings,
    )
    return TestClient(
        create_app(config, engine, provider or FakeEmbeddingClient(), task_queue=queue)
    )


class RecordingNotifier:
    def __init__(self) -> None:
        self.records: list[MatchRecord] = []

    def notify(self, match: MatchRecord) -> None:
        self.records.append(match)


class FailingNotifier(RecordingNotifier):
    def notify(self, match: MatchRecord) -> None:
        super().notify(match)
        raise ConnectionError("pub/sub is down")


def seed_job(engine: Engine, **fields: Any) -> int:
    """A job with an extraction (`fields` override extraction fields, `title` and so on)."""
    options = {
        key: fields.pop(key) for key in ("title", "company", "location", "source") if key in fields
    }
    published = fields.pop("published_at", None)
    return add_search_job(
        engine, extraction=extraction_data(**fields), published_at=published, **options
    )


def index_all(engine: Engine) -> FakeEmbeddingClient:
    client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    index_pending(INDEX_CFG, client, apply=True, db_engine=engine)
    return client


def reindex(engine: Engine, *job_ids: int) -> None:
    client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    index_jobs(list(job_ids), INDEX_CFG, client, engine)


def change_extraction(engine: Engine, job_id: int, **fields: Any) -> None:
    """Replace fields of the job's extraction (the posting changed) without indexing."""
    posting_id = representative_posting_id(engine, job_id)
    with engine.begin() as conn:
        data = conn.execute(
            select(PostingExtraction.data).where(PostingExtraction.posting_id == posting_id)
        ).scalar_one()
        conn.execute(
            update(PostingExtraction)
            .where(PostingExtraction.posting_id == posting_id)
            .values(data={**data, **fields})
        )


def match_rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(select(JobMatch).order_by(JobMatch.id))
        return [dict(row._mapping) for row in rows]


def set_published(engine: Engine, job_id: int, published_at: Any) -> None:
    posting_id = representative_posting_id(engine, job_id)
    with engine.begin() as conn:
        conn.execute(
            update(Posting).where(Posting.id == posting_id).values(published_at=published_at)
        )
