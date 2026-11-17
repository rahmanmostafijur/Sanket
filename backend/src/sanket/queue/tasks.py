"""The tasks of the matching pipeline: names, payload shapes and idempotency keys.

A key says "this exact piece of work", so enqueueing it twice while it is pending is one task:

- `embed_profile`: a profile id and the content hash to embed; saving the same content twice
  queues once.
- `match_job`: a job id and the hash of its current embedding; a job whose embedding did not
  change is never matched again.
- `match_profile`: a profile id, its content hash and the hash of its embedding.
"""

from pydantic import BaseModel, ConfigDict, Field

TASK_EMBED_PROFILE = "embed_profile"
TASK_MATCH_JOB = "match_job"
TASK_MATCH_PROFILE = "match_profile"

# Stands in for the embedding hash of a job that has no embedding any more (it died), so
# the task that withdraws its matches has a key of its own.
NO_EMBEDDING = "none"


class EmbedProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=100)


class MatchJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
    embedding_hash: str = Field(min_length=1, max_length=100)


class MatchProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=100)
    embedding_hash: str = Field(min_length=1, max_length=100)


def embed_profile_key(profile_id: int, content_hash: str) -> str:
    return f"{profile_id}-{content_hash}"


def match_job_key(job_id: int, embedding_hash: str) -> str:
    return f"{job_id}-{embedding_hash}"


def match_profile_key(profile_id: int, content_hash: str, embedding_hash: str) -> str:
    return f"{profile_id}-{content_hash}-{embedding_hash}"
