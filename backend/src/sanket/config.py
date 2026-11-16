from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    test_database_url: str | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    # Free-tier limit for gemini-3.5-flash-lite as reported by the API on 2026-11-12.
    gemini_requests_per_minute: int = Field(default=15, ge=1)

    # Ingestion. Lists are comma-separated in the environment.
    ingest_sources: CommaList = []
    greenhouse_boards: CommaList = []
    lever_companies: CommaList = []
    ashby_boards: CommaList = []
    himalayas_api_key: SecretStr | None = None
    # USAJOBS needs both: the key, and the email address it was registered with, which the
    # API takes as the User-Agent. Without them the source is skipped.
    usajobs_api_key: SecretStr | None = None
    usajobs_user_agent_email: str | None = None
    # JobTech Sweden: optional free-text query, pages of 100 ads per run (the API allows 20),
    # and how far back to look for ads published since.
    jobtech_query: str | None = None
    jobtech_max_pages: int = Field(default=5, ge=1, le=20)
    jobtech_lookback_days: int = Field(default=2, ge=1, le=30)

    # Group postings into canonical jobs at the end of every ingest run. A failure is logged and
    # never fails the run; turn it off if the job table has not been migrated yet.
    canonicalise_after_ingest: bool = True

    @field_validator(
        "ingest_sources",
        "greenhouse_boards",
        "lever_companies",
        "ashby_boards",
        "extraction_excluded_sources",
        mode="before",
    )
    @classmethod
    def _split_comma_list(cls, value: object) -> object:
        # Board tokens and company slugs are used as given, so case is preserved.
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    # Extraction cost guards and data-use rules.
    extraction_batch_limit: int = Field(default=50, ge=1)
    extraction_max_description_chars: int = Field(default=12000, ge=500)
    extraction_max_attempts: int = Field(default=3, ge=1)
    # Remote OK reserves AI training on its data; on the Gemini free tier, API inputs may be
    # used to improve Google's models, so Remote OK postings are not sent by default.
    extraction_excluded_sources: CommaList = ["remoteok"]

    # Indexing and embeddings (see docs/adr/0003-job-indexing.md). The vector column is fixed
    # at 768 dimensions by migration; EMBEDDING_DIMENSIONS must match it, which the indexing
    # CLI checks at startup. Free-tier embedding quotas are small: keep the pacing and the
    # batch size conservative and check the limits shown for the key in Google AI Studio.
    embedding_model: str = "gemini-embedding-001"
    # Our own label for a (model, settings) combination. Bump it to embed every job again
    # next to the existing vectors, for example after changing the document format.
    embedding_model_version: str = Field(default="1", min_length=1)
    embedding_dimensions: int = Field(default=768, ge=1)
    embedding_requests_per_minute: int = Field(default=30, ge=1)
    embedding_batch_size: int = Field(default=20, ge=1, le=100)
    # Jobs that need work (new or changed) handled per indexing run.
    indexing_batch_limit: int = Field(default=500, ge=1)
    # Description excerpt in the search document. The embedding model reads at most 2048 tokens
    # and Bengali or Swedish text takes more tokens per character than English, so keep it modest.
    indexing_max_description_chars: int = Field(default=3000, ge=200)
    # pgvector hnsw.ef_search: candidates examined per vector query (recall against speed).
    hnsw_ef_search: int = Field(default=100, ge=1, le=1000)

    @field_validator(
        "himalayas_api_key",
        "gemini_api_key",
        "jobtech_query",
        "usajobs_api_key",
        "usajobs_user_agent_email",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # An unset GitHub Actions secret or variable arrives as an empty string.
        if isinstance(value, str) and not value.strip():
            return None
        return value


# database_url has no default and is read from the environment, which mypy cannot see.
settings = Settings()  # type: ignore[call-arg]
