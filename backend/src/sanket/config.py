from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

CommaList = Annotated[list[str], NoDecode]

Environment = Literal["development", "test", "production"]

if TYPE_CHECKING:
    # Tests and callers build Settings with plain strings; pydantic turns them into SecretStr.
    SecretInput = SecretStr | str
else:
    SecretInput = SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Where this process runs. Anything but "development" refuses the development shortcuts
    # (see sanket.runtime_checks) and "production" is what the container images set.
    environment: Environment = "development"
    # The URLs carry the database password, so they are secrets: read them with
    # `database_dsn` where a connection is made and nowhere else.
    database_url: SecretInput
    test_database_url: SecretInput | None = None
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

    # Search (see docs/adr/0004-search-design.md). Candidates per ranked list (full text and
    # vector) before fusion; it is also the deepest page reachable. RRF k and the per-list
    # weights of the fusion. The query-embedding cache holds this many entries in process.
    search_candidates: int = Field(default=100, ge=1, le=1000)
    search_rrf_k: int = Field(default=60, ge=1)
    search_fulltext_weight: float = Field(default=1.0, ge=0)
    search_vector_weight: float = Field(default=1.0, ge=0)
    search_query_cache_size: int = Field(default=1000, ge=0)
    # A search waits at most this long for the query embedding before falling back to
    # full-text results only.
    search_embedding_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # Task queue (see docs/adr/0005-task-queue.md). Without REDIS_URL nothing is queued: the
    # API still saves profiles and the indexing run still succeeds, and the pending work is
    # picked up later by `python -m sanket.matching` (docs/matching.md). The URL may carry a
    # password, so it is a secret.
    redis_url: SecretStr | None = None
    queue_name: str = Field(
        default="sanket", min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$"
    )
    # Attempts per task in total (the first run included) and the delay before each retry:
    # base * factor ** (retry number - 1), capped.
    queue_max_attempts: int = Field(default=5, ge=1, le=20)
    queue_backoff_base_seconds: float = Field(default=30.0, gt=0)
    queue_backoff_factor: float = Field(default=2.0, ge=1)
    queue_backoff_max_seconds: float = Field(default=3600.0, gt=0)
    # A task running longer than this is treated as dead and its slot is released.
    queue_task_timeout_seconds: int = Field(default=600, ge=10)
    # How long a dead-lettered task is kept for inspection and requeueing.
    queue_dead_letter_ttl_days: int = Field(default=30, ge=1)
    # Redis connect and read timeouts, so an unreachable Redis fails fast in a request.
    redis_timeout_seconds: float = Field(default=3.0, gt=0, le=60)

    # Profiles and matching (see docs/adr/0006-profiles-and-matching.md). Until authentication
    # exists every request acts as this owner; the authenticated principal replaces it.
    default_owner_id: str = Field(default="default", min_length=1, max_length=100)
    max_profiles_per_owner: int = Field(default=20, ge=1, le=1000)
    # Queue a matching task for every job whose embedding changed in an indexing run.
    # Only effective when REDIS_URL is set.
    match_enqueue_after_indexing: bool = True
    # A match must reach this blended score (0 to 1), and its embedding cosine similarity
    # must reach MATCH_MIN_COSINE. The cosine component of the score is rescaled from
    # MATCH_MIN_COSINE (0) to 1 (1). Defaults are reasoned starting points, not tuned values.
    match_min_score: float = Field(default=0.55, ge=0, le=1)
    match_min_cosine: float = Field(default=0.5, ge=0, lt=1)
    match_weight_cosine: float = Field(default=0.6, ge=0)
    match_weight_skills: float = Field(default=0.25, ge=0)
    match_weight_title: float = Field(default=0.15, ge=0)
    # Share of a profile's required skills a job must list (1.0 means all of them).
    match_required_skills_min_fraction: float = Field(default=1.0, gt=0, le=1)
    # Nearest stored profiles examined for a changed job, then scored exactly.
    match_max_profiles_per_job: int = Field(default=200, ge=1, le=5000)
    # Jobs examined for a changed profile: seen within this many days, nearest first, at most
    # this many.
    match_recent_job_days: int = Field(default=30, ge=1, le=365)
    match_max_jobs_per_profile: int = Field(default=200, ge=1, le=5000)

    # The API server. Loopback by default; bind to another address deliberately.
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # Authentication (docs/adr/0008-authentication.md). Callers send `Authorization: Bearer`
    # with a JWT (signed with AUTH_JWT_SECRET, or by a provider whose keys are at
    # AUTH_JWKS_URL) or one of the static AUTH_API_KEYS (`owner=key,owner2=key2`). The token
    # subject (AUTH_OWNER_CLAIM) is the owner id. AUTH_DEV_BYPASS lets requests without a
    # credential act as DEFAULT_OWNER_ID; it only works with ENVIRONMENT=development.
    auth_dev_bypass: bool = False
    auth_jwt_secret: SecretStr | None = None
    auth_jwks_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)
    auth_owner_claim: str = Field(default="sub", min_length=1, max_length=50)
    auth_required_scope: str | None = None
    auth_api_keys: SecretStr | None = None
    # Signs the short-lived tokens that let a browser EventSource (which cannot send headers)
    # open the match stream. Unset disables them.
    auth_stream_token_secret: SecretStr | None = None
    auth_stream_token_ttl_seconds: int = Field(default=60, ge=10, le=600)
    # GET /search costs an embedding call per query. It requires authentication unless this
    # is true, in which case it is open (and rate limited by client address).
    search_public: bool = False

    @field_validator(
        "himalayas_api_key",
        "gemini_api_key",
        "jobtech_query",
        "usajobs_api_key",
        "usajobs_user_agent_email",
        "redis_url",
        "auth_jwt_secret",
        "auth_jwks_url",
        "auth_issuer",
        "auth_audience",
        "auth_required_scope",
        "auth_api_keys",
        "auth_stream_token_secret",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # An unset GitHub Actions secret or variable arrives as an empty string.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def database_dsn(self) -> str:
        """The database URL, with its password. Use it only where the connection is made."""
        url = self.database_url
        return url if isinstance(url, str) else url.get_secret_value()


# database_url has no default and is read from the environment, which mypy cannot see.
settings = Settings()  # type: ignore[call-arg]
