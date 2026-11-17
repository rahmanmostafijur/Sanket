"""Small, composable steps of the whole backend pipeline, for the end-to-end tests.

Everything runs in this process against the test database, with recorded payloads and fakes:
no network, no Redis, no real LLM or embedding provider. The steps mirror the production
chain (ingest, canonicalise, extract, index, match) and call the same functions the commands
and the worker call; only the I/O at the edges is replaced:

- HTTP: an `httpx.MockTransport` serves the recorded payloads (`fetcher_for`).
- LLM: `KeyedExtractionClient`, a `ScriptedClient` that answers by posting title.
- Embeddings: `FakeEmbeddingClient`.
- Queue: `InMemoryTaskQueue`, drained with the real task registry (`drain_queue`).
- Notifier: `RecordingNotifier`, which counts as "delivered" like the default `NoopNotifier`.

A test composes the steps it needs around a `Stack`, which carries the shared fakes.

EXTENSION POINTS (the final integration appends stages here instead of rewriting the tests):

- Live feed delivery (SSE, phase 7). `Stack.notifier` is the `MatchNotifier` handed to the
  matching tasks. Build the stack with the real notifier (`build_stack(engine, notifier=...)`)
  and add steps that subscribe to a profile's stream and read events before and after
  `run_pipeline`. The persisted match ids are the event ids: compare them with `matches_of`.
- Authenticated requests (phase 8). `api_client` forwards `dependencies` (FastAPI dependencies
  applied to every route) and any `Settings` overrides to `create_app`; pass the auth
  dependency and the auth settings there, and add the credentials as default headers of the
  returned client. Profile calls must then be made as two different users to assert scoping.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
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
from tests.e2e.data import EXTRACTIONS
from tests.index_helpers import CFG as INDEX_CFG
from tests.index_helpers import SPEC
from tests.match_helpers import RecordingNotifier
from tests.source_helpers import json_handler, make_fetcher
from tests.test_llm import ScriptedClient

OWNER = "e2e-owner"
# The fake embedding is a bag of hashed words, so its cosines are small and say little about
# fit. These thresholds let the profile's hard filters decide, which is what the tests assert.
# The window is wide so the recorded (fixed) dates never age out of "recent jobs".
MATCH_CFG = MatchConfig(spec=SPEC, min_cosine=-1.0, min_score=0.0, recent_job_days=36500)
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


def build_stack(engine: Engine, notifier: RecordingNotifier | MatchNotifier | None = None) -> Stack:
    config = Settings.model_validate(
        {
            "database_url": engine.url.render_as_string(hide_password=False),
            "embedding_model": SPEC.model_name,
            "embedding_model_version": SPEC.model_version,
            "embedding_dimensions": SPEC.dimensions,
            "default_owner_id": OWNER,
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
    return dict(run_batch(stack.llm, EXTRACTION_CFG, 100, stack.engine))


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


def api_client(stack: Stack, dependencies: Sequence[Depends] = (), **settings: Any) -> TestClient:
    """A client for the app wired to the stack (extension point for authenticated requests)."""
    config = stack.settings.model_copy(update=settings)
    return TestClient(
        create_app(
            config,
            stack.engine,
            stack.embedder,
            task_queue=stack.queue,
            dependencies=dependencies,
        )
    )


def search(client: TestClient, q: str, **params: Any) -> dict[str, Any]:
    response = client.get("/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def search_titles(client: TestClient, q: str, **params: Any) -> list[str]:
    return [item["title"] for item in search(client, q, **params)["items"]]


def create_profile(client: TestClient, body: Mapping[str, Any]) -> dict[str, Any]:
    response = client.post("/profiles", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def matches_of(
    client: TestClient, profile_id: int, *, include_withdrawn: bool = False
) -> list[dict[str, Any]]:
    response = client.get(
        f"/profiles/{profile_id}/matches",
        params={"include_withdrawn": include_withdrawn, "limit": 100},
    )
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def matched_titles(client: TestClient, profile_id: int) -> list[str]:
    return sorted(match["job"]["title"] for match in matches_of(client, profile_id))


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
