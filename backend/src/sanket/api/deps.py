"""What request handlers share: the application context, read from `app.state`."""

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine

from sanket.embeddings.client import EmbeddingClient
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.retrieval import SearchConfig


@dataclass(frozen=True)
class ApiContext:
    db_engine: Engine
    search_config: SearchConfig
    # None when no embedding provider is configured: search then answers from full text only.
    embedding_client: EmbeddingClient | None
    query_cache: QueryEmbeddingCache


def get_context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context
