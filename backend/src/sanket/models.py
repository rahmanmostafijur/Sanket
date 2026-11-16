from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Width of job_embedding.embedding. Fixed by the migration that created the column; changing it
# is a new migration plus a full re-embed (docs/adr/0003-job-indexing.md). EMBEDDING_DIMENSIONS
# in the settings must equal it, which the indexing CLI checks at startup.
EMBEDDING_COLUMN_DIMENSIONS = 768
# HNSW build parameters (pgvector defaults): links per node, and the candidate list size while
# building. Higher values give better recall and a slower, larger index.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Posting(Base):
    __tablename__ = "posting"
    __table_args__ = (UniqueConstraint("source", "source_id"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # The canonical job this posting belongs to. NULL until it has been canonicalised, and
    # for postings with no usable title or company.
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )


class Job(Base):
    """The canonical entity that groups the postings describing one real job.

    `fingerprint` is the versioned hash of the normalised company, title and location
    (`sanket.canonical.fingerprint`). The display fields and the aggregates are copied from
    the member postings by `sanket.canonical`; `representative_posting_id` is the member
    that supplies the display fields. A job whose last posting moved away keeps its row with
    `posting_count` 0, so ids that other tables refer to stay valid. Whether a job is still
    open is not stored: it is answered at query time from `last_seen_at`.
    """

    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("fingerprint"),
        CheckConstraint("posting_count >= 0", name="posting_count_nonnegative"),
        Index("ix_job_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    # use_alter breaks the posting <-> job foreign key cycle for metadata table sorting.
    representative_posting_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posting.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    posting_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Full-text document, written by `sanket.indexing` from the job, its representative
    # posting and that posting's extraction (so it cannot be a generated column). NULL until
    # indexed, and for jobs with no postings. `search_hash` is the hash it was built from.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    search_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobEmbedding(Base):
    """The vector of a job for one embedding model.

    Rows for different `(model_name, model_version)` pairs coexist, so a new model can be
    filled in while the old one keeps serving. `content_hash` covers the embedded text, the
    model, its version, the dimension and the document format: the row is written again only
    when it changes. The vector column has a fixed width (EMBEDDING_COLUMN_DIMENSIONS) and
    `dimension` records it, checked against the vector itself by the database.
    """

    __tablename__ = "job_embedding"
    __table_args__ = (
        UniqueConstraint("job_id", "model_name", "model_version"),
        CheckConstraint("dimension = vector_dims(embedding)", name="dimension_matches_vector"),
        Index(
            "ix_job_embedding_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_COLUMN_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceRequest(Base):
    """One HTTP request attempt to a job source, used for daily request budgets."""

    __tablename__ = "source_request"
    __table_args__ = (Index("ix_source_request_source_requested_at", "source", "requested_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostingExtraction(Base):
    """Latest extraction of a posting for one (schema_version, prompt_version) pair.

    `content_hash` is the posting hash that was extracted; when the posting changes, the
    row is re-extracted and overwritten. `attempts` counts runs for that content hash, and
    the token columns hold the usage of the latest run, repairs included.
    """

    __tablename__ = "posting_extraction"
    __table_args__ = (
        UniqueConstraint("posting_id", "schema_version", "prompt_version"),
        CheckConstraint("status IN ('ok', 'failed')", name="status_valid"),
        CheckConstraint("status <> 'ok' OR data IS NOT NULL", name="ok_has_data"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    posting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posting.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmbeddingStatus:
    """Where a profile's embedding stands, `profile.embedding_status`."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MatchStatus:
    """`job_match.status`. A match that stops holding is kept, withdrawn, so its id is stable."""

    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class Profile(Base):
    """What one user is looking for (docs/adr/0006-profiles-and-matching.md).

    `owner_id` is an opaque identifier of the owner; every query is scoped by it. `criteria`
    is the validated `sanket.profiles.criteria.ProfileCriteria` as JSON. `search_text` is the
    text that is embedded and `content_hash` covers the criteria and `active`, so an
    unchanged save re-embeds and re-matches nothing. A profile is deleted for real, which
    removes its embeddings and matches.
    """

    __tablename__ = "profile"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        CheckConstraint(
            "embedding_status IN ('pending', 'ready', 'failed')", name="embedding_status_valid"
        ),
        Index("ix_profile_owner_id_id", "owner_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # `pending` from every content change until the embedding for that content exists,
    # `failed` when the latest attempt to embed it failed; only `ready` profiles are matched.
    embedding_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", nullable=False
    )
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProfileEmbedding(Base):
    """The vector of a profile for one embedding model; same conventions as `JobEmbedding`."""

    __tablename__ = "profile_embedding"
    __table_args__ = (
        UniqueConstraint("profile_id", "model_name", "model_version"),
        CheckConstraint("dimension = vector_dims(embedding)", name="dimension_matches_vector"),
        Index(
            "ix_profile_embedding_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_COLUMN_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobMatch(Base):
    """A job scored against a profile (docs/adr/0006-profiles-and-matching.md).

    One row per (profile, job), written by `INSERT ... ON CONFLICT DO UPDATE`, so repeating a
    run changes nothing. `id` only ever grows (identity), which is what the match feed uses as
    its event id and resume point; a row keeps its id for life, also when the match is
    `withdrawn` (the job no longer passes) and again `active`. `components` explains the
    score. `job_embedding_hash` and `profile_hash` identify what it was scored against, and
    `scorer_version` the algorithm. `notified_at` is set once the notification hook ran and
    reset when a withdrawn match becomes active again.
    """

    __tablename__ = "job_match"
    __table_args__ = (
        UniqueConstraint("profile_id", "job_id"),
        CheckConstraint("status IN ('active', 'withdrawn')", name="status_valid"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_in_range"),
        Index("ix_job_match_profile_id_id", "profile_id", "id"),
        Index("ix_job_match_job_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("job.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Double, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scorer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="active", nullable=False)
    job_embedding_hash: Mapped[str] = mapped_column(Text, nullable=False)
    profile_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
