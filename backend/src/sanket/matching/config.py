"""Matching configuration, built from the settings."""

from dataclasses import dataclass

from sanket.config import Settings
from sanket.embeddings.client import EmbeddingSpec


@dataclass(frozen=True)
class MatchConfig:
    spec: EmbeddingSpec
    min_score: float = 0.55
    min_cosine: float = 0.5
    weight_cosine: float = 0.6
    weight_skills: float = 0.25
    weight_title: float = 0.15
    required_skills_min_fraction: float = 1.0
    max_profiles_per_job: int = 200
    recent_job_days: int = 30
    max_jobs_per_profile: int = 200
    ef_search: int | None = None


def config_from_settings(config: Settings) -> MatchConfig:
    return MatchConfig(
        spec=EmbeddingSpec(
            model_name=config.embedding_model,
            model_version=config.embedding_model_version,
            dimensions=config.embedding_dimensions,
        ),
        min_score=config.match_min_score,
        min_cosine=config.match_min_cosine,
        weight_cosine=config.match_weight_cosine,
        weight_skills=config.match_weight_skills,
        weight_title=config.match_weight_title,
        required_skills_min_fraction=config.match_required_skills_min_fraction,
        max_profiles_per_job=config.match_max_profiles_per_job,
        recent_job_days=config.match_recent_job_days,
        max_jobs_per_profile=config.match_max_jobs_per_profile,
        ef_search=config.hnsw_ef_search,
    )
