"""Application factory.

Everything the app depends on is passed in, so tests run it against the test database with a
fake embedding client and nothing global is touched at import time. Omit `embedding_client`
to build the real one from the settings (or none, without a key); pass None to disable
embeddings explicitly. `task_queue` works the same way (the Redis queue when REDIS_URL is set,
else none); the profile endpoints queue their embedding work on it. `feed_redis` opens the
Redis clients the live match feed subscribes with (none without REDIS_URL, and the streams then
poll the database).

Authentication is built from the settings (`sanket.auth`, docs/adr/0008-authentication.md);
`dependencies` is applied to every API route on top of it. The settings are checked first
(`sanket.runtime_checks.check_api`), so a misconfigured API does not start.
"""

import logging
from collections.abc import Sequence
from typing import Final

from fastapi import FastAPI
from fastapi.params import Depends
from sqlalchemy import Engine

from sanket.accounts.tokens import access_tokens_from_settings
from sanket.api.deps import ApiContext
from sanket.api.errors import install_error_handlers
from sanket.api.health import ReadinessProbe, checks_from_settings
from sanket.api.limits import RateLimit
from sanket.api.middleware import RequestContextMiddleware
from sanket.api.routers import accounts as accounts_router
from sanket.api.routers import auth as auth_router
from sanket.api.routers import cv as cv_router
from sanket.api.routers import feed as feed_router
from sanket.api.routers import jobs as jobs_router
from sanket.api.routers import me as me_router
from sanket.api.routers import ops as ops_router
from sanket.api.routers import profiles as profiles_router
from sanket.api.routers import saved as saved_router
from sanket.api.routers import search as search_router
from sanket.auth.authenticator import authenticator_from_settings
from sanket.auth.stream_token import StreamTokens
from sanket.config import Settings
from sanket.config import settings as default_settings
from sanket.cv.service import cv_client_from_settings
from sanket.db import engine as default_engine
from sanket.embeddings.client import EmbeddingClient, spec_of
from sanket.extraction.llm import LlmClient
from sanket.feed.config import config_from_settings as feed_config_from_settings
from sanket.feed.connection import redis_factory_from_settings
from sanket.feed.limits import StreamLimiter
from sanket.feed.subscription import RedisFactory
from sanket.observability.metrics import ApiMetrics
from sanket.observability.tracing import setup_tracing
from sanket.observability.worker_metrics import worker_collector_for
from sanket.queue.base import TaskQueue
from sanket.queue.connection import task_queue_from_settings
from sanket.ratelimit.factory import limiter_from_settings
from sanket.ratelimit.limiter import MemoryRateLimiter, RateLimiter
from sanket.ratelimit.policy import limits_from_settings
from sanket.runtime_checks import check_api
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.client import query_embedding_client
from sanket.search.retrieval import search_config_from_settings

API_TITLE = "Sanket"
API_VERSION = "0.1.0"


class _UseSettings:
    """Marker: build the embedding client from the settings."""


USE_SETTINGS: Final = _UseSettings()

logger = logging.getLogger(__name__)


def _stream_tokens(config: Settings) -> StreamTokens | None:
    if config.auth_stream_token_secret is None:
        return None
    return StreamTokens(
        config.auth_stream_token_secret.get_secret_value(), config.auth_stream_token_ttl_seconds
    )


def _metrics(config: Settings, queue: TaskQueue | None) -> ApiMetrics | None:
    """Metrics are served unless switched off, and without a token only outside production."""
    if not config.metrics_enabled:
        return None
    if config.metrics_token is None and config.is_production:
        logger.info("metrics are off: set METRICS_TOKEN to serve /metrics in production")
        return None
    return ApiMetrics(queue, worker_collector=worker_collector_for(queue, config))


def _metrics_token(config: Settings) -> str | None:
    return config.metrics_token.get_secret_value() if config.metrics_token else None


def create_app(
    settings: Settings | None = None,
    db_engine: Engine | None = None,
    embedding_client: EmbeddingClient | None | _UseSettings = USE_SETTINGS,
    task_queue: TaskQueue | None | _UseSettings = USE_SETTINGS,
    rate_limiter: RateLimiter | None | _UseSettings = USE_SETTINGS,
    dependencies: Sequence[Depends] = (),
    feed_redis: RedisFactory | None | _UseSettings = USE_SETTINGS,
    llm_client: LlmClient | None | _UseSettings = USE_SETTINGS,
) -> FastAPI:
    config = settings or default_settings
    check_api(config)
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
    feed_config = feed_config_from_settings(config)
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    install_error_handlers(app)
    engine_in_use = db_engine or default_engine
    queue = task_queue_from_settings(config) if isinstance(task_queue, _UseSettings) else task_queue
    limiter = (
        limiter_from_settings(config) if isinstance(rate_limiter, _UseSettings) else rate_limiter
    )
    metrics = _metrics(config, queue)
    app.add_middleware(
        RequestContextMiddleware, observer=metrics.observe_request if metrics else None
    )
    context = ApiContext(
        db_engine=engine_in_use,
        search_config=search_config,
        embedding_client=client,
        query_cache=QueryEmbeddingCache(config.search_query_cache_size),
        task_queue=queue,
        default_owner_id=config.default_owner_id,
        max_profiles_per_owner=config.max_profiles_per_owner,
        feed_config=feed_config,
        feed_limiter=StreamLimiter(feed_config.max_streams, feed_config.max_streams_per_profile),
        feed_redis=(
            redis_factory_from_settings(config)
            if isinstance(feed_redis, _UseSettings)
            else feed_redis
        ),
        authenticator=authenticator_from_settings(config),
        stream_tokens=_stream_tokens(config),
        access_tokens=access_tokens_from_settings(config),
        limiter=limiter,
        auth_limiter=limiter or MemoryRateLimiter(),
        llm_client=cv_client_from_settings(config)
        if isinstance(llm_client, _UseSettings)
        else llm_client,
        rate_limits=limits_from_settings(config),
        readiness=ReadinessProbe(
            checks_from_settings(config, engine_in_use), config.readyz_timeout_seconds
        ),
        metrics=metrics,
        metrics_token=_metrics_token(config),
    )
    app.state.context = context
    guard = list(dependencies)
    standard = [Depends(RateLimit("default")), *guard]
    app.include_router(search_router.router, dependencies=[Depends(RateLimit("search")), *guard])
    app.include_router(jobs_router.router, dependencies=[Depends(RateLimit("search")), *guard])
    app.include_router(me_router.router, dependencies=standard)
    app.include_router(cv_router.router, dependencies=standard)
    app.include_router(profiles_router.router, dependencies=standard)
    app.include_router(saved_router.router, dependencies=standard)
    app.include_router(auth_router.router, dependencies=standard)
    # Sign-up and log-in carry their own, stricter limits (per address and per email).
    app.include_router(accounts_router.router, dependencies=guard)
    # Streams are exempt from the per-request rate limit; the feed caps open streams instead.
    app.include_router(feed_router.router, dependencies=guard)
    app.include_router(ops_router.router)
    setup_tracing(app, engine_in_use, config)
    return app
