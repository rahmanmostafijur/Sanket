"""A deterministic embedding client for tests and offline development.

Vectors are built from word hashes, so two texts that share words have a positive cosine
similarity that grows with the overlap, and unrelated texts are close to orthogonal. That is
enough to make retrieval tests meaningful without any network call. Not a real model: never
use it to fill a real index.
"""

import hashlib
import re
from collections.abc import Callable, Sequence

from sanket.embeddings.client import EmbeddingError, l2_normalise

WORD = re.compile(r"\w+")


class FakeEmbeddingClient:
    """Records every call. `fail_when(texts)` may return an EmbeddingError to raise."""

    def __init__(
        self,
        dimensions: int = 768,
        model_name: str = "fake-embedding",
        model_version: str = "1",
        fail_when: Callable[[Sequence[str]], EmbeddingError | None] | None = None,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.dimensions = dimensions
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []
        self._fail_when = fail_when

    @property
    def texts_embedded(self) -> int:
        return sum(len(call) for call in self.document_calls)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        if self._fail_when is not None:
            failure = self._fail_when(texts)
            if failure is not None:
                raise failure
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in WORD.findall(text.casefold()):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        if not any(vector):
            vector[0] = 1.0
        return l2_normalise(vector)
