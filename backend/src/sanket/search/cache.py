"""A small bounded in-process cache for query embeddings.

Embedding a query costs a provider call; people repeat queries, and paging repeats the same
query for every page. The cache is keyed by the embedding model and the normalised query, so a
change of model never serves a stale vector. It is least-recently-used, thread safe (the API
serves requests from a thread pool) and per process: with several workers each has its own.
A size of 0 turns it off.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable

from sanket.embeddings.client import EmbeddingSpec


def normalise_query(text: str) -> str:
    """Collapse whitespace and ignore case, so trivially different spellings share an entry."""
    return " ".join(text.split()).casefold()


class QueryEmbeddingCache:
    def __init__(self, max_size: int) -> None:
        if max_size < 0:
            raise ValueError("max_size must not be negative")
        self._max_size = max_size
        self._entries: OrderedDict[tuple[str, str, int, str], tuple[float, ...]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get_or_embed(
        self, spec: EmbeddingSpec, query: str, embed: Callable[[str], list[float]]
    ) -> list[float]:
        """The cached vector of `query`, or `embed(query)` stored for next time.

        A failing `embed` raises and stores nothing. The provider call runs outside the lock,
        so two simultaneous first requests for one query may both call it; the second result
        simply replaces the first.
        """
        key = (spec.model_name, spec.model_version, spec.dimensions, normalise_query(query))
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None:
                self._entries.move_to_end(key)
                return list(hit)
        vector = embed(query)
        if self._max_size > 0:
            with self._lock:
                self._entries[key] = tuple(vector)
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_size:
                    self._entries.popitem(last=False)
        return vector
