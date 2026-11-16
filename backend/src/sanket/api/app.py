"""Application factory.

Everything the app depends on is passed in, so tests run it against the test database with a
fake embedding client and nothing global is touched at import time. Omit `embedding_client`
to build the real one from the settings (or none, without a key); pass None to disable
embeddings explicitly.

Authentication is not built yet. `dependencies` is applied to every route, which is where an
auth dependency goes when it exists (`create_app(dependencies=[Depends(require_user)])`).
"""

import logging
from collections.abc import Sequence
from typing import Final

from fastapi import FastAPI
from fastapi.params import Depends
from pydantic import SecretStr
from sqlalchemy import Engine

from sanket.api.deps import ApiContext
from sanket.api.routers import search as search_router
from sanket.config import Settings
from sanket.config import settings as default_settings
from sanket.db import engine as default_engine
from sanket.embeddings.client import EmbeddingClient, spec_of
from sanket.embeddings.gemini import GeminiEmbeddingClient
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.retrieval import search_config_from_settings

API_TITLE = "Sanket"
API_VERSION = "0.1.0"
# A search should fail over to full text quickly rather than wait out the indexer's patient
# retry schedule (2s, 8s, 32s).
QUERY_EMBEDDING_ATTEMPTS = 2
MS_PER_SECOND = 1000


class _UseSettings:
    """Marker: build the embedding client from the settings."""


USE_SETTINGS: Final = _UseSettings()

logger = logging.getLogger(__name__)


def query_embedding_client(config: Settings) -> EmbeddingClient | None:
    """The Gemini client for query embeddings, tuned to fail fast; None without a key."""
    key: SecretStr | None = config.gemini_api_key
    if key is None:
        logger.warning("GEMINI_API_KEY is not set: search will use full text only")
        return None
    return GeminiEmbeddingClient(
        key,
        config.embedding_model,
        config.embedding_dimensions,
        model_version=config.embedding_model_version,
        retry_attempts=QUERY_EMBEDDING_ATTEMPTS,
        timeout_ms=int(config.search_embedding_timeout_seconds * MS_PER_SECOND),
    )


def create_app(
    settings: Settings | None = None,
    db_engine: Engine | None = None,
    embedding_client: EmbeddingClient | None | _UseSettings = USE_SETTINGS,
    dependencies: Sequence[Depends] = (),
) -> FastAPI:
    config = settings or default_settings
    search_config = search_config_from_settings(config)
    client = (
        query_embedding_client(config)
        if isinstance(embedding_client, _UseSettings)
        else embedding_client
    )
    if client is not None and spec_of(client) != search_config.spec:
        raise ValueError(
            f"the embedding client produces {spec_of(client)} but the index is searched with "
            f"{search_config.spec}"
        )
    app = FastAPI(title=API_TITLE, version=API_VERSION, dependencies=list(dependencies))
    context = ApiContext(
        db_engine=db_engine or default_engine,
        search_config=search_config,
        embedding_client=client,
        query_cache=QueryEmbeddingCache(config.search_query_cache_size),
    )
    app.state.context = context
    app.include_router(search_router.router)
    return app
