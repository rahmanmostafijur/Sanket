"""Provider-neutral embedding interface, shared by the indexing worker and search."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class EmbeddingError(Exception):
    """An embedding call failed or returned something unusable.

    `retryable` is False when the provider rejected the input itself (a 4xx other than a
    quota error), so repeating the same request cannot help; callers may then try the texts
    one by one to find the offending one. Quota, server and network errors, and malformed
    responses, are retryable: the same request may succeed on a later run.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class EmbeddingSpec:
    """Which vectors a client produces: what a stored embedding is keyed and hashed by."""

    model_name: str
    model_version: str
    dimensions: int


class EmbeddingClient(Protocol):
    model_name: str
    model_version: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One unit-length vector per text, in order, for text that will be searched."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """The unit-length vector of a search query."""
        ...


def spec_of(client: EmbeddingClient) -> EmbeddingSpec:
    return EmbeddingSpec(client.model_name, client.model_version, client.dimensions)


def l2_normalise(vector: Sequence[float]) -> list[float]:
    """Scale to unit length; raises EmbeddingError for an all-zero vector."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0 or not math.isfinite(norm):
        raise EmbeddingError("embedding has zero or non-finite length")
    return [value / norm for value in vector]


def check_vectors(
    vectors: Sequence[Sequence[float]], expected_count: int, dimensions: int
) -> list[list[float]]:
    """Return the vectors as lists after checking their number and dimension."""
    if len(vectors) != expected_count:
        raise EmbeddingError(f"expected {expected_count} embeddings, got {len(vectors)}")
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError(f"expected {dimensions} dimensions, got {len(vector)}")
    return [list(vector) for vector in vectors]
