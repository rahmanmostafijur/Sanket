"""Read what matching needs: job and profile views, embeddings and the nearest neighbours.

The vector queries use the HNSW indexes of `job_embedding` and `profile_embedding` with the
same session settings as search (`hnsw.ef_search`, iterative scan), and cosine similarity is
`1 - cosine distance`. Only vectors of the configured model name and version are compared.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, func, select

from sanket.config import settings
from sanket.db import engine
from sanket.embeddings.client import EmbeddingSpec
from sanket.indexing.queries import ITERATIVE_SCAN_MODE, MAX_EF_SEARCH
from sanket.indexing.service import parse_extraction
from sanket.matching.config import MatchConfig
from sanket.matching.types import JobView, ProfileView
from sanket.models import EmbeddingStatus, Job, JobEmbedding, Profile, ProfileEmbedding
from sanket.profiles.store import ProfileRow
from sanket.search.details import load_details

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"


@dataclass(frozen=True)
class StoredVector:
    """An embedding as stored, with the hash of what it was built from."""

    entity_id: int
    content_hash: str
    embedding: list[float]


def _set_scan_options(conn: Connection, limit: int, ef_search: int | None) -> None:
    effective = min(max(ef_search or settings.hnsw_ef_search, limit), MAX_EF_SEARCH)
    conn.execute(select(func.set_config("hnsw.ef_search", str(effective), True)))
    conn.execute(select(func.set_config("hnsw.iterative_scan", ITERATIVE_SCAN_MODE, True)))


def load_job_vector(conn: Connection, job_id: int, spec: EmbeddingSpec) -> StoredVector | None:
    """The embedding of a job that still has postings, or None."""
    stmt = (
        select(JobEmbedding.job_id, JobEmbedding.content_hash, JobEmbedding.embedding)
        .join(Job, Job.id == JobEmbedding.job_id)
        .where(
            JobEmbedding.job_id == job_id,
            JobEmbedding.model_name == spec.model_name,
            JobEmbedding.model_version == spec.model_version,
            Job.posting_count > 0,
        )
    )
    row = conn.execute(stmt).one_or_none()
    return None if row is None else StoredVector(row[0], row[1], list(row[2]))


def load_profile_vector(
    conn: Connection, profile_id: int, spec: EmbeddingSpec
) -> StoredVector | None:
    stmt = select(
        ProfileEmbedding.profile_id, ProfileEmbedding.content_hash, ProfileEmbedding.embedding
    ).where(
        ProfileEmbedding.profile_id == profile_id,
        ProfileEmbedding.model_name == spec.model_name,
        ProfileEmbedding.model_version == spec.model_version,
    )
    row = conn.execute(stmt).one_or_none()
    return None if row is None else StoredVector(row[0], row[1], list(row[2]))


def nearest_profiles(
    vector: Sequence[float], cfg: MatchConfig, db_engine: Engine = engine
) -> list[tuple[int, float]]:
    """`(profile_id, cosine)` of the active, embedded profiles nearest to a job, best first."""
    distance = ProfileEmbedding.embedding.cosine_distance(list(vector))
    stmt = (
        select(ProfileEmbedding.profile_id, distance.label("distance"))
        .join(Profile, Profile.id == ProfileEmbedding.profile_id)
        .where(
            ProfileEmbedding.model_name == cfg.spec.model_name,
            ProfileEmbedding.model_version == cfg.spec.model_version,
            Profile.active.is_(True),
            Profile.embedding_status == EmbeddingStatus.READY,
        )
        .order_by(distance, ProfileEmbedding.profile_id)
        .limit(cfg.max_profiles_per_job)
    )
    with db_engine.begin() as conn:
        _set_scan_options(conn, cfg.max_profiles_per_job, cfg.ef_search)
        rows = conn.execute(stmt).all()
    return [(profile_id, 1.0 - float(dist)) for profile_id, dist in rows]


def job_cosines(
    conn: Connection, job_ids: Sequence[int], vector: Sequence[float], spec: EmbeddingSpec
) -> dict[int, tuple[str, float]]:
    """`(embedding hash, cosine)` of each of these jobs that still has postings and an
    embedding for `spec`, measured exactly (not through the index)."""
    if not job_ids:
        return {}
    distance = JobEmbedding.embedding.cosine_distance(list(vector))
    stmt = (
        select(JobEmbedding.job_id, JobEmbedding.content_hash, distance)
        .join(Job, Job.id == JobEmbedding.job_id)
        .where(
            JobEmbedding.job_id.in_(job_ids),
            JobEmbedding.model_name == spec.model_name,
            JobEmbedding.model_version == spec.model_version,
            Job.posting_count > 0,
        )
    )
    return {row[0]: (row[1], 1.0 - float(row[2])) for row in conn.execute(stmt)}


def load_profile_views(
    conn: Connection, profile_ids: Sequence[int]
) -> tuple[dict[int, ProfileView], dict[int, ProfileRow]]:
    """Views of these profiles (and their rows, for the status). One whose stored criteria no
    longer validate is left out and logged."""
    views: dict[int, ProfileView] = {}
    rows: dict[int, ProfileRow] = {}
    if not profile_ids:
        return views, rows
    for row in conn.execute(select(Profile).where(Profile.id.in_(profile_ids))):
        profile = ProfileRow(**row._mapping)
        rows[profile.id] = profile
        try:
            views[profile.id] = ProfileView.from_row(profile)
        except ValidationError:
            logger.warning("Profile %d: stored criteria do not validate, skipped", profile.id)
    return views, rows


def load_job_views(
    job_ids: Sequence[int], hashes: Mapping[int, str], db_engine: Engine = engine
) -> dict[int, JobView]:
    """Views of these jobs (those in `hashes`, which carries each one's embedding hash)."""
    details = load_details([job_id for job_id in job_ids if job_id in hashes], db_engine)
    views: dict[int, JobView] = {}
    for job_id, detail in details.items():
        extraction = parse_extraction(detail.extraction, job_id)
        views[job_id] = JobView(
            job_id=job_id,
            title=detail.title,
            location=detail.location,
            seniority=_known(extraction.seniority.value) if extraction else None,
            work_mode=_known(extraction.work_mode.value) if extraction else None,
            employment_type=_known(extraction.employment_type.value) if extraction else None,
            country=str(extraction.country) if extraction and extraction.country else None,
            skills=tuple(extraction.skills) if extraction else (),
            embedding_hash=hashes[job_id],
        )
    return views


def _known(value: str) -> str | None:
    return None if value == UNKNOWN else value
