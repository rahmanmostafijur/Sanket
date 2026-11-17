"""Small, composable steps of the whole backend pipeline, for the end-to-end tests.

Everything runs in this process against the test database, with recorded payloads and fakes:
no network, no real Redis, no real LLM or embedding provider. The steps mirror the production
chain (ingest, canonicalise, extract, index, match) and call the same functions the commands
and the worker call; only the I/O at the edges is replaced:

- HTTP: an `httpx.MockTransport` serves the recorded payloads (`fetcher_for`).
- LLM: `KeyedExtractionClient`, a `ScriptedClient` that answers by posting title.
- Embeddings: `FakeEmbeddingClient`.
- Queue: `InMemoryTaskQueue`, drained with the real task registry (`drain_queue`).
- Notifier: `RecordingNotifier`, which counts as "delivered" like the default `NoopNotifier`
  (the live feed stack uses the real `RedisMatchNotifier` on fakeredis instead).

A test composes the steps it needs around a `Stack`, which carries the shared fakes.

LIVE FEED: `build_feed_stack` builds the stack with the real `RedisMatchNotifier` publishing to
a fake Redis (`Stack.redis`), and `api_app` gives the app whose streams subscribe to it. The
stage itself is in `tests/e2e/test_feed_e2e.py`, with the ASGI stream client in `sse.py`.

AUTHENTICATION: `build_auth_stack` builds a feed stack whose app needs real credentials (bearer
JWTs, an API key, stream tokens; no development bypass). The stage is in
`tests/e2e/test_auth_e2e.py`. Every other stack uses `auth_dev_bypass`, so its requests act as
`default_owner_id` (`api_client(stack, default_owner_id="someone")` simulates a second owner).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.params import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select

from sanket.api import create_app
from sanket.canonical.service import CanonicaliseSummary, canonicalise
from sanket.config import Settings
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.extraction.llm import ChatMessage, LlmResponse
from sanket.extraction.runner import ExtractionConfig, Outcome, run_batch
from sanket.indexing.service import IndexSummary, index_pending
from sanket.ingest import SourceSummary, run_source
from sanket.matching.config import MatchConfig
from sanket.matching.notify import MatchNotifier
from sanket.matching.tasks import MatchTaskDeps, build_registry
from sanket.matching.triggers import index_observer
from sanket.models import Job, JobEmbedding, JobMatch, Posting
from sanket.queue.memory import InMemoryTaskQueue
from sanket.sources.base import Source
from sanket.storage import save_postings
from tests import auth_helpers
from tests.e2e.data import EXTRACTIONS
from tests.feed_helpers import PREFIX as FEED_PREFIX
from tests.feed_helpers import FakeRedisSide
from tests.index_helpers import CFG as INDEX_CFG
from tests.index_helpers import SPEC
from tests.match_helpers import RecordingNotifier
from tests.source_helpers import json_handler, make_fetcher
from tests.test_llm import ScriptedClient

OWNER = "e2e-owner"
# The owner the static API key of the authenticated stack belongs to.
API_KEY_OWNER = "ops"
# The fake embedding is a bag of hashed words, so its cosines are small and say little about
# fit. These thresholds let the profile's hard filters decide, which is what the tests assert.
# The window is wide so the recorded (fixed) dates never age out of "recent jobs".
MATCH_CFG = MatchConfig(spec=SPEC, min_cosine=-1.0, min_score=0.0, recent_job_days=36500)
# Short, so an open stream shows it is idle (and waiting for Redis) within a blink.
HEARTBEAT_SECONDS = 0.05
EXTRACTION_CFG = ExtractionConfig(model="scripted", max_description_chars=2000, max_attempts=3)


class KeyedExtractionClient(ScriptedClient):
    """Answers each extraction with the document registered for the title in the prompt.

    A positional script would depend on the order the postings are extracted in; this one
    only depends on what the posting says. An unknown title fails loudly.
    """

    def __init__(self, documents: Mapping[str, Mapping[str, Any]]) -> None:
        super().__init__([])
        self._documents = dict(documents)

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict
    ) -> LlmResponse:
        self.conversations.append(list(messages))
        text = messages[0].text
        for title, document in self._documents.items():
            if f"Title: {title}\n" in text:
                return LlmResponse(json.dumps(document), 10, 5)
        raise AssertionError(f"no scripted extraction for this posting:\n{text[:200]}")


@dataclass(frozen=True)
class Stack:
    """The database plus the fakes every step shares."""

    engine: Engine
    embedder: FakeEmbeddingClient
    queue: InMemoryTaskQueue
    notifier: RecordingNotifier | MatchNotifier
    llm: KeyedExtractionClient
    settings: Settings
    # The fake Redis the notifier publishes to and the streams subscribe to (feed stacks only).
    redis: FakeRedisSide | None = None


def build_stack(
    engine: Engine,
    notifier: RecordingNotifier | MatchNotifier | None = None,
    **settings: Any,
) -> Stack:
    config = Settings.model_validate(
        {
            "database_url": engine.url.render_as_string(hide_password=False),
            "embedding_model": SPEC.model_name,
            "embedding_model_version": SPEC.model_version,
            "embedding_dimensions": SPEC.dimensions,
            "default_owner_id": OWNER,
            # Requests without credentials act as `default_owner_id` unless a test is about
            # authentication and builds its stack with `auth_dev_bypass=False` (see
            # `build_auth_stack`).
            "auth_dev_bypass": True,
            **settings,
        }
    )
    return Stack(
        engine=engine,
        embedder=FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version),
        queue=InMemoryTaskQueue(),
        notifier=notifier or RecordingNotifier(),
        llm=KeyedExtractionClient(EXTRACTIONS),
        settings=config,
    )


def build_feed_stack(engine: Engine, **settings: Any) -> Stack:
    """A stack whose notifier is the real `RedisMatchNotifier` on a fake Redis, and whose app
    streams from that same Redis. Intervals are tiny so nothing waits."""
    redis = FakeRedisSide()
    stack = build_stack(
        engine,
        notifier=redis.notifier,
        feed_channel_prefix=FEED_PREFIX,
        feed_heartbeat_seconds=HEARTBEAT_SECONDS,
        feed_db_poll_seconds=0.02,
        **settings,
    )
    return replace(stack, redis=redis)


def build_auth_stack(engine: Engine, **settings: Any) -> Stack:
    """A feed stack whose app needs real credentials: bearer JWTs (HS256), one API key and
    stream tokens, and no development bypass (see `tests/auth_helpers.py` for the credentials)."""
    return build_feed_stack(
        engine,
        auth_dev_bypass=False,
        auth_jwt_secret=auth_helpers.SECRET,
        auth_api_keys=f"{API_KEY_OWNER}={auth_helpers.API_KEY}",
        auth_stream_token_secret=auth_helpers.STREAM_SECRET,
        **settings,
    )


# -- the pipeline, one stage at a time ----------------------------------------------------------


def fetcher_for(payloads: Mapping[str, object]) -> Any:
    """A Fetcher that answers each URL (query string ignored) with the recorded JSON payload."""

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        if url not in payloads:
            return httpx.Response(404, json={"error": f"not recorded: {url}"})
        return json_handler(payloads[url])(request)

    return make_fetcher(handle)


def ingest(stack: Stack, source: Source, payloads: Mapping[str, object]) -> SourceSummary:
    """Run one source adapter against the recorded payloads and save what it fetched."""
    return run_source(
        source,
        fetcher_for(payloads),
        None,
        datetime.now(UTC),
        save=lambda rows: save_postings(rows, stack.engine),
    )


def canonicalise_all(stack: Stack) -> CanonicaliseSummary:
    return canonicalise(stack.engine, apply=True)


def extract_pending(stack: Stack) -> dict[Outcome, int]:
    return dict(run_batch(stack.llm, EXTRACTION_CFG, 100, stack.engine).counts)


def index_all(stack: Stack) -> IndexSummary:
    """Index every job that needs it; the observer queues matching for what changed."""
    observer = index_observer(stack.settings, stack.queue)
    return index_pending(
        INDEX_CFG, stack.embedder, apply=True, db_engine=stack.engine, on_changes=observer
    )


def drain_queue(stack: Stack) -> int:
    """Run the queued tasks (and the ones they chain) with the real matching handlers."""
    deps = MatchTaskDeps(
        cfg=MATCH_CFG,
        embedder=stack.embedder,
        queue=stack.queue,
        notifier=stack.notifier,
        db_engine=stack.engine,
    )
    return stack.queue.run_pending(build_registry(deps))


@dataclass(frozen=True)
class PipelineRun:
    """What one pass over the chain reported."""

    ingested: tuple[SourceSummary, ...]
    canonical: CanonicaliseSummary
    extraction: dict[Outcome, int]
    indexing: IndexSummary
    tasks_run: int


def run_pipeline(stack: Stack, feeds: Sequence[tuple[Source, Mapping[str, object]]]) -> PipelineRun:
    """ingest -> canonicalise -> extract -> index -> run the matching tasks that indexing queued."""
    ingested = tuple(ingest(stack, source, payloads) for source, payloads in feeds)
    canonical = canonicalise_all(stack)
    extraction = extract_pending(stack)
    indexing = index_all(stack)
    return PipelineRun(ingested, canonical, extraction, indexing, drain_queue(stack))


# -- the API ------------------------------------------------------------------------------------


def api_app(stack: Stack, dependencies: Sequence[Depends] = (), **settings: Any) -> FastAPI:
    """The app wired to the stack (extension point for authenticated requests)."""
    config = stack.settings.model_copy(update=settings)
    return create_app(
        config,
        stack.engine,
        stack.embedder,
        task_queue=stack.queue,
        dependencies=dependencies,
        feed_redis=stack.redis.factory if stack.redis else None,
    )


def api_client(stack: Stack, dependencies: Sequence[Depends] = (), **settings: Any) -> TestClient:
    return TestClient(api_app(stack, dependencies, **settings))


# The calls below take the credentials of an authenticated stack as `headers`; stacks that
# use the development bypass need none.
Headers = Mapping[str, str] | None


def search(client: TestClient, q: str, headers: Headers = None, **params: Any) -> dict[str, Any]:
    response = client.get("/search", params={"q": q, **params}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def search_titles(client: TestClient, q: str, headers: Headers = None, **params: Any) -> list[str]:
    return [item["title"] for item in search(client, q, headers, **params)["items"]]


def create_profile(
    client: TestClient, body: Mapping[str, Any], headers: Headers = None
) -> dict[str, Any]:
    response = client.post("/profiles", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def matches_of(
    client: TestClient,
    profile_id: int,
    *,
    include_withdrawn: bool = False,
    headers: Headers = None,
) -> list[dict[str, Any]]:
    response = client.get(
        f"/profiles/{profile_id}/matches",
        params={"include_withdrawn": include_withdrawn, "limit": 100},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def matched_titles(client: TestClient, profile_id: int, headers: Headers = None) -> list[str]:
    return sorted(
        match["job"]["title"] for match in matches_of(client, profile_id, headers=headers)
    )


# -- reading and changing the database ----------------------------------------------------------


@dataclass(frozen=True)
class IndexState:
    jobs: int
    with_search_vector: int
    embeddings: int
    live_jobs: int


def index_state(engine: Engine) -> IndexState:
    with engine.connect() as conn:
        return IndexState(
            jobs=conn.execute(select(func.count()).select_from(Job)).scalar_one(),
            with_search_vector=conn.execute(
                select(func.count()).select_from(Job).where(Job.search_vector.is_not(None))
            ).scalar_one(),
            embeddings=conn.execute(select(func.count()).select_from(JobEmbedding)).scalar_one(),
            live_jobs=conn.execute(
                select(func.count()).select_from(Job).where(Job.posting_count > 0)
            ).scalar_one(),
        )


def job_titles_by_posting_count(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {row.title: row.posting_count for row in conn.execute(select(Job))}


def match_snapshot(engine: Engine) -> list[tuple[Any, ...]]:
    """Every stored match with the columns a rerun must not change."""
    stmt = select(
        JobMatch.id,
        JobMatch.profile_id,
        JobMatch.job_id,
        JobMatch.status,
        JobMatch.score,
        JobMatch.updated_at,
        JobMatch.notified_at,
    ).order_by(JobMatch.id)
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(stmt)]


def remove_posting(engine: Engine, source: str, source_id: str) -> None:
    """Delete a posting, as when a listing is taken down and cleaned up."""
    stmt = delete(Posting).where(Posting.source == source, Posting.source_id == source_id)
    with engine.begin() as conn:
        conn.execute(stmt)
