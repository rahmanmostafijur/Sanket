from pydantic import SecretStr

from sanket.config import Settings
from sanket.embeddings.client import spec_of
from sanket.embeddings.gemini import GeminiEmbeddingClient
from sanket.search.client import QUERY_EMBEDDING_ATTEMPTS, query_embedding_client

DATABASE_URL = "postgresql+psycopg://u:p@127.0.0.1:5433/x_test"


def test_without_a_key_there_is_no_client() -> None:
    config = Settings(database_url=DATABASE_URL, gemini_api_key=None)

    assert query_embedding_client(config) is None


def test_with_a_key_the_client_matches_the_index_and_fails_fast() -> None:
    config = Settings(
        database_url=DATABASE_URL,
        gemini_api_key=SecretStr("test-key"),
        embedding_model="gemini-embedding-001",
        embedding_model_version="3",
    )

    client = query_embedding_client(config)

    assert isinstance(client, GeminiEmbeddingClient)
    spec = spec_of(client)
    assert (spec.model_name, spec.model_version, spec.dimensions) == (
        "gemini-embedding-001",
        "3",
        config.embedding_dimensions,
    )
    assert QUERY_EMBEDDING_ATTEMPTS < 4  # fewer than the indexer's patient retry schedule
    assert client._retry_attempts == QUERY_EMBEDDING_ATTEMPTS
