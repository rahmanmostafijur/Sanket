"""What request handlers share: the application context, read from `app.state`."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine

from sanket.embeddings.client import EmbeddingClient
from sanket.feed.config import FeedConfig
from sanket.feed.limits import StreamLimiter
from sanket.feed.subscription import RedisFactory
from sanket.queue.base import TaskQueue
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.retrieval import SearchConfig


@dataclass(frozen=True)
class ApiContext:
    db_engine: Engine
    search_config: SearchConfig
    # None when no embedding provider is configured: search then answers from full text only.
    embedding_client: EmbeddingClient | None
    query_cache: QueryEmbeddingCache
    # None when Redis is not configured: profiles are saved and wait to be embedded.
    task_queue: TaskQueue | None
    # Who every request acts as until authentication exists (see `get_owner_id`).
    default_owner_id: str
    max_profiles_per_owner: int
    feed_config: FeedConfig
    feed_limiter: StreamLimiter
    # Opens a Redis client for one stream; None when Redis is not configured (streams then
    # poll the database).
    feed_redis: RedisFactory | None


def get_context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


def get_owner_id(context: Annotated[ApiContext, Depends(get_context)]) -> str:
    """The opaque id of the owner a request acts for.

    Until authentication exists this is DEFAULT_OWNER_ID. The authentication phase replaces
    this dependency with one that maps the authenticated principal onto an owner id; every
    profile query is already scoped by whatever it returns.
    """
    return context.default_owner_id
