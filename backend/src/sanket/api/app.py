"""Application factory.

Everything the app depends on is passed in, so tests run it against the test database with a
fake embedding client and nothing global is touched at import time. Omit `embedding_client`
to build the real one from the settings (or none, without a key); pass None to disable
embeddings explicitly. `task_queue` works the same way (the Redis queue when REDIS_URL is set,
else none); the profile endpoints queue their embedding work on it.

Authentication is not built yet. `dependencies` is applied to every route, which is where an
auth dependency goes when it exists (`create_app(dependencies=[Depends(require_user)])`).
"""

import logging
from collections.abc import Sequence
from typing import Final

from fastapi import FastAPI
from fastapi.params import Depends
from sqlalchemy import Engine

from sanket.api.deps import ApiContext
from sanket.api.routers import profiles as profiles_router
from sanket.api.routers import search as search_router
from sanket.config import Settings
from sanket.config import settings as default_settings
from sanket.db import engine as default_engine
from sanket.embeddings.client import EmbeddingClient, spec_of
from sanket.queue.base import TaskQueue
from sanket.queue.connection import task_queue_from_settings
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.client import query_embedding_client
from sanket.search.retrieval import search_config_from_settings

API_TITLE = "Sanket"
API_VERSION = "0.1.0"


class _UseSettings:
    """Marker: build the embedding client from the settings."""


USE_SETTINGS: Final = _UseSettings()

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    db_engine: Engine | None = None,
    embedding_client: EmbeddingClient | None | _UseSettings = USE_SETTINGS,
    task_queue: TaskQueue | None | _UseSettings = USE_SETTINGS,
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
        task_queue=(
            task_queue_from_settings(config) if isinstance(task_queue, _UseSettings) else task_queue
        ),
        default_owner_id=config.default_owner_id,
        max_profiles_per_owner=config.max_profiles_per_owner,
    )
    app.state.context = context
    app.include_router(search_router.router)
    app.include_router(profiles_router.router)
    return app
