"""The embedding client used to embed search queries."""

import logging

from sanket.config import Settings
from sanket.embeddings.client import EmbeddingClient
from sanket.embeddings.gemini import GeminiEmbeddingClient

# A search should fail over to full text quickly rather than wait out the indexer's patient
# retry schedule (2s, 8s, 32s).
QUERY_EMBEDDING_ATTEMPTS = 2
MS_PER_SECOND = 1000

logger = logging.getLogger(__name__)


def query_embedding_client(config: Settings) -> EmbeddingClient | None:
    """The Gemini client for query embeddings, tuned to fail fast; None without a key.

    No request pacing: a quota per user or per minute is the rate limiting of a later phase,
    and the in-process cache already spares repeated queries.
    """
    if config.gemini_api_key is None:
        logger.warning("GEMINI_API_KEY is not set: search will use full text only")
        return None
    return GeminiEmbeddingClient(
        config.gemini_api_key,
        config.embedding_model,
        config.embedding_dimensions,
        model_version=config.embedding_model_version,
        retry_attempts=QUERY_EMBEDDING_ATTEMPTS,
        timeout_ms=int(config.search_embedding_timeout_seconds * MS_PER_SECOND),
    )
