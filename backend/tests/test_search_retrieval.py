"""Retrieval and fusion with the two candidate queries replaced by fixed ranked lists."""

from collections.abc import Sequence
from typing import Any

import pytest

from sanket.config import Settings
from sanket.embeddings.client import EmbeddingError, EmbeddingSpec
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.filters import SearchFilters
from sanket.indexing.queries import Candidate
from sanket.search import retrieval
from sanket.search.cache import QueryEmbeddingCache
from sanket.search.retrieval import (
    REASON_EMBEDDING_FAILED,
    REASON_EMBEDDINGS_DISABLED,
    SearchConfig,
    SearchMode,
    matched_by,
    retrieve,
    search_config_from_settings,
)

SPEC = EmbeddingSpec("fake-embedding", "1", 768)
CFG = SearchConfig(
    spec=SPEC, candidates=100, rrf_k=60, fulltext_weight=1.0, vector_weight=1.0, ef_search=100
)


def ranked(*job_ids: int) -> list[Candidate]:
    return [Candidate(job_id, rank, 0.0) for rank, job_id in enumerate(job_ids, 1)]


class Calls:
    def __init__(self) -> None:
        self.text: list[dict[str, Any]] = []
        self.vector: list[dict[str, Any]] = []


@pytest.fixture
def stub_queries(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """The text list is [10, 20, 30] and the vector list is [20, 40, 10]."""
    calls = Calls()

    def text(
        query: str, limit: int, db_engine: object = None, *, filters: SearchFilters | None = None
    ) -> list[Candidate]:
        calls.text.append({"query": query, "limit": limit, "filters": filters})
        return ranked(10, 20, 30)[:limit]

    def vector(
        embedding: Sequence[float],
        spec: EmbeddingSpec,
        limit: int,
        ef_search: int | None = None,
        db_engine: object = None,
        *,
        filters: SearchFilters | None = None,
    ) -> list[Candidate]:
        calls.vector.append({"limit": limit, "filters": filters, "ef_search": ef_search})
        return ranked(20, 40, 10)[:limit]

    monkeypatch.setattr(retrieval, "fulltext_candidates", text)
    monkeypatch.setattr(retrieval, "vector_candidates", vector)
    return calls


class FailingClient(FakeEmbeddingClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        raise self.error


def test_hybrid_order_matches_the_hand_computed_fusion(stub_queries: Calls) -> None:
    # text [10, 20, 30], vector [20, 40, 10], k = 60:
    #   10: 1/61 + 1/63 = 0.032266   20: 1/62 + 1/61 = 0.032522
    #   30: 1/63 = 0.015873          40: 1/62 = 0.016129
    result = retrieve("q", SearchFilters(), CFG, FakeEmbeddingClient())

    assert [item.job_id for item in result.items] == [20, 10, 40, 30]
    assert [round(item.score, 6) for item in result.items] == [
        0.032522,
        0.032266,
        0.016129,
        0.015873,
    ]
    assert [matched_by(item) for item in result.items] == ["both", "both", "vector", "text"]
    assert not result.degraded


def test_weights_change_the_order(stub_queries: Calls) -> None:
    cfg = SearchConfig(SPEC, 100, 60, fulltext_weight=3.0, vector_weight=1.0)

    result = retrieve("q", SearchFilters(), cfg, FakeEmbeddingClient())

    # 10: 3/61 + 1/63 = 0.0650   20: 3/62 + 1/61 = 0.0648   30: 3/63   40: 1/62
    assert [item.job_id for item in result.items] == [10, 20, 30, 40]


def test_the_fused_list_is_capped_at_the_candidate_count(stub_queries: Calls) -> None:
    cfg = SearchConfig(SPEC, 3, 60, 1.0, 1.0)

    result = retrieve("q", SearchFilters(), cfg, FakeEmbeddingClient())

    assert len(result.items) == 3
    assert stub_queries.text[0]["limit"] == 3
    assert stub_queries.vector[0]["limit"] == 3


def test_filters_and_ef_search_reach_both_queries(stub_queries: Calls) -> None:
    filters = SearchFilters(work_modes=("remote",))

    retrieve("q", filters, CFG, FakeEmbeddingClient())

    assert stub_queries.text[0]["filters"] == filters
    assert stub_queries.vector[0]["filters"] == filters
    assert stub_queries.vector[0]["ef_search"] == 100


def test_a_failing_embedding_degrades_to_full_text(stub_queries: Calls) -> None:
    client = FailingClient(EmbeddingError("quota"))

    result = retrieve("q", SearchFilters(), CFG, client)

    assert [item.job_id for item in result.items] == [10, 20, 30]
    assert result.degraded
    assert result.degraded_reason == REASON_EMBEDDING_FAILED
    assert {matched_by(item) for item in result.items} == {"text"}
    assert stub_queries.vector == []


def test_an_unexpected_provider_exception_also_degrades(stub_queries: Calls) -> None:
    result = retrieve("q", SearchFilters(), CFG, FailingClient(TimeoutError("slow")))

    assert result.degraded
    assert result.degraded_reason == REASON_EMBEDDING_FAILED
    assert len(result.items) == 3


def test_no_client_means_embeddings_are_disabled(stub_queries: Calls) -> None:
    result = retrieve("q", SearchFilters(), CFG, None)

    assert result.degraded
    assert result.degraded_reason == REASON_EMBEDDINGS_DISABLED
    assert [item.job_id for item in result.items] == [10, 20, 30]


def test_text_mode_never_embeds_and_is_not_degraded(stub_queries: Calls) -> None:
    client = FakeEmbeddingClient()

    result = retrieve("q", SearchFilters(), CFG, client, mode=SearchMode.TEXT)

    assert [item.job_id for item in result.items] == [10, 20, 30]
    assert not result.degraded
    assert client.query_calls == []
    assert stub_queries.vector == []


def test_vector_mode_uses_the_vector_list_only(stub_queries: Calls) -> None:
    result = retrieve("q", SearchFilters(), CFG, FakeEmbeddingClient(), mode=SearchMode.VECTOR)

    assert [item.job_id for item in result.items] == [20, 40, 10]
    assert {matched_by(item) for item in result.items} == {"vector"}
    assert stub_queries.text == []


def test_a_zero_weight_switches_a_list_off_without_calling_the_provider(
    stub_queries: Calls,
) -> None:
    client = FakeEmbeddingClient()
    cfg = SearchConfig(SPEC, 100, 60, fulltext_weight=1.0, vector_weight=0.0)

    result = retrieve("q", SearchFilters(), cfg, client)

    assert [item.job_id for item in result.items] == [10, 20, 30]
    assert client.query_calls == []
    assert not result.degraded


def test_a_zero_text_weight_does_not_empty_a_text_only_run(stub_queries: Calls) -> None:
    cfg = SearchConfig(SPEC, 100, 60, fulltext_weight=0.0, vector_weight=1.0)

    result = retrieve("q", SearchFilters(), cfg, None, mode=SearchMode.TEXT)

    assert [item.job_id for item in result.items] == [10, 20, 30]


def test_the_embedded_query_is_whitespace_normalised_and_cached(stub_queries: Calls) -> None:
    client = FakeEmbeddingClient()
    cache = QueryEmbeddingCache(10)

    retrieve("  python   dev ", SearchFilters(), CFG, client, cache=cache)
    retrieve("Python dev", SearchFilters(), CFG, client, cache=cache)

    assert client.query_calls == ["python dev"]


def test_a_failed_embedding_is_not_cached(stub_queries: Calls) -> None:
    cache = QueryEmbeddingCache(10)
    failing = FailingClient(EmbeddingError("down"))
    healthy = FakeEmbeddingClient()

    retrieve("q", SearchFilters(), CFG, failing, cache=cache)
    result = retrieve("q", SearchFilters(), CFG, healthy, cache=cache)

    assert not result.degraded
    assert healthy.query_calls == ["q"]


def test_config_is_built_from_settings() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/x_test",
        search_candidates=7,
        search_rrf_k=30,
        search_fulltext_weight=2.0,
        search_vector_weight=0.5,
        embedding_model="m",
        embedding_model_version="9",
    )

    cfg = search_config_from_settings(settings)

    assert (cfg.candidates, cfg.rrf_k, cfg.fulltext_weight, cfg.vector_weight) == (7, 30, 2.0, 0.5)
    assert cfg.spec == EmbeddingSpec("m", "9", settings.embedding_dimensions)
