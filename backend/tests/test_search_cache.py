import threading

import pytest

from sanket.embeddings.client import EmbeddingSpec
from sanket.search.cache import QueryEmbeddingCache, normalise_query

SPEC = EmbeddingSpec("model", "1", 3)


class CountingEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        return [float(len(self.calls)), 0.0, 0.0]


def test_normalisation_collapses_whitespace_and_case() -> None:
    assert normalise_query("  Python \t Developer\n") == "python developer"


def test_a_repeated_query_is_embedded_once() -> None:
    cache = QueryEmbeddingCache(5)
    embed = CountingEmbedder()

    first = cache.get_or_embed(SPEC, "Python Dev", embed)
    second = cache.get_or_embed(SPEC, "  python   dev", embed)

    assert first == second
    assert len(embed.calls) == 1


def test_the_model_is_part_of_the_key() -> None:
    cache = QueryEmbeddingCache(5)
    embed = CountingEmbedder()

    cache.get_or_embed(SPEC, "q", embed)
    cache.get_or_embed(EmbeddingSpec("model", "2", 3), "q", embed)
    cache.get_or_embed(EmbeddingSpec("other", "1", 3), "q", embed)

    assert len(embed.calls) == 3


def test_the_least_recently_used_entry_is_evicted() -> None:
    cache = QueryEmbeddingCache(2)
    embed = CountingEmbedder()
    cache.get_or_embed(SPEC, "a", embed)
    cache.get_or_embed(SPEC, "b", embed)
    cache.get_or_embed(SPEC, "a", embed)  # a is now the most recent
    cache.get_or_embed(SPEC, "c", embed)  # evicts b

    assert len(cache) == 2
    cache.get_or_embed(SPEC, "a", embed)
    assert len(embed.calls) == 3
    cache.get_or_embed(SPEC, "b", embed)
    assert len(embed.calls) == 4


def test_size_zero_disables_the_cache() -> None:
    cache = QueryEmbeddingCache(0)
    embed = CountingEmbedder()

    cache.get_or_embed(SPEC, "q", embed)
    cache.get_or_embed(SPEC, "q", embed)

    assert len(embed.calls) == 2
    assert len(cache) == 0


def test_a_failing_embedder_stores_nothing() -> None:
    cache = QueryEmbeddingCache(5)

    def boom(text: str) -> list[float]:
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        cache.get_or_embed(SPEC, "q", boom)

    assert len(cache) == 0


def test_a_negative_size_is_rejected() -> None:
    with pytest.raises(ValueError):
        QueryEmbeddingCache(-1)


def test_returned_vectors_are_copies() -> None:
    cache = QueryEmbeddingCache(5)
    embed = CountingEmbedder()
    first = cache.get_or_embed(SPEC, "q", embed)
    first.append(99.0)

    assert cache.get_or_embed(SPEC, "q", embed) == [1.0, 0.0, 0.0]


def test_concurrent_use_stays_within_the_bound() -> None:
    cache = QueryEmbeddingCache(4)
    embed = CountingEmbedder()

    def work(n: int) -> None:
        for i in range(50):
            cache.get_or_embed(SPEC, f"q{(n * 7 + i) % 10}", embed)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(cache) <= 4
