import math
from collections.abc import Sequence
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types
from pydantic import SecretStr

from sanket.embeddings.client import EmbeddingError, l2_normalise, spec_of
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.embeddings.gemini import (
    MAX_TEXTS_PER_REQUEST,
    RETRY_ATTEMPTS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_DELAY_FACTOR,
    TASK_DOCUMENT,
    TASK_QUERY,
    GeminiEmbeddingClient,
)

DIMENSIONS = 8


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


class StubGenai:
    """Stands in for genai.Client: `.models.embed_content` returns or raises the script."""

    def __init__(self, script: Sequence[object]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []
        self.models = SimpleNamespace(embed_content=self._embed_content)

    def _embed_content(self, *, model: str, contents: list[str], config: types.EmbedContentConfig):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._script[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def response(*vectors: Sequence[float]) -> SimpleNamespace:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=list(v)) for v in vectors])


def gemini(stub: StubGenai, sleeps: list[float] | None = None, **kwargs) -> GeminiEmbeddingClient:
    record = sleeps if sleeps is not None else []
    return GeminiEmbeddingClient(
        SecretStr("test-key"),
        "gemini-embedding-001",
        DIMENSIONS,
        client=stub,  # type: ignore[arg-type]
        sleep=record.append,
        **kwargs,
    )


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": "boom", "status": "ERR"}})


# --- fake client -------------------------------------------------------------------------


def test_fake_vectors_are_deterministic_unit_length_with_the_right_dimension() -> None:
    fake = FakeEmbeddingClient(dimensions=64)

    first = fake.embed_documents(["python backend engineer"])[0]
    second = fake.embed_query("python backend engineer")

    assert first == second
    assert len(first) == 64
    assert norm(first) == pytest.approx(1.0)


def test_fake_similarity_grows_with_shared_words() -> None:
    fake = FakeEmbeddingClient()
    query = fake.embed_query("python postgres engineer")
    close, far = fake.embed_documents(
        ["senior python postgres engineer in berlin", "pastry chef in paris"]
    )

    assert cosine(query, close) > 0.5
    assert abs(cosine(query, far)) < 0.2


def test_fake_handles_text_with_no_words_and_records_calls() -> None:
    fake = FakeEmbeddingClient()

    assert norm(fake.embed_documents(["!!!"])[0]) == pytest.approx(1.0)
    fake.embed_documents(["a", "b"])
    fake.embed_query("q")

    assert fake.texts_embedded == 3
    assert len(fake.document_calls) == 2
    assert fake.query_calls == ["q"]
    assert spec_of(fake).dimensions == 768


def test_fake_can_be_told_to_fail() -> None:
    fake = FakeEmbeddingClient(fail_when=lambda texts: EmbeddingError("down"))

    with pytest.raises(EmbeddingError):
        fake.embed_documents(["a"])


def test_l2_normalise_rejects_a_zero_vector() -> None:
    assert l2_normalise([3.0, 4.0]) == [0.6, 0.8]
    with pytest.raises(EmbeddingError):
        l2_normalise([0.0, 0.0])


# --- Gemini client -----------------------------------------------------------------------


def test_documents_use_the_document_task_and_requested_dimensions() -> None:
    stub = StubGenai([response([3.0] + [0.0] * 7, [0.0, 2.0] + [0.0] * 6)])

    vectors = gemini(stub).embed_documents(["first", "second"])

    (call,) = stub.calls
    assert call["model"] == "gemini-embedding-001"
    assert call["contents"] == ["first", "second"]
    assert call["config"].task_type == TASK_DOCUMENT
    assert call["config"].output_dimensionality == DIMENSIONS
    assert vectors == [[1.0] + [0.0] * 7, [0.0, 1.0] + [0.0] * 6]


def test_query_uses_the_query_task_and_is_normalised() -> None:
    stub = StubGenai([response([0.0, 0.0, 5.0] + [0.0] * 5)])

    vector = gemini(stub).embed_query("python")

    assert stub.calls[0]["config"].task_type == TASK_QUERY
    assert norm(vector) == pytest.approx(1.0)
    assert vector[2] == pytest.approx(1.0)


def test_large_batches_are_split_into_requests_of_the_provider_maximum() -> None:
    texts = [f"t{i}" for i in range(MAX_TEXTS_PER_REQUEST + 1)]
    stub = StubGenai(
        [
            response(*([[1.0] * DIMENSIONS] * MAX_TEXTS_PER_REQUEST)),
            response([1.0] * DIMENSIONS),
        ]
    )

    vectors = gemini(stub).embed_documents(texts)

    assert [len(call["contents"]) for call in stub.calls] == [MAX_TEXTS_PER_REQUEST, 1]
    assert len(vectors) == len(texts)


def test_retries_quota_errors_with_growing_delays_then_succeeds() -> None:
    stub = StubGenai([api_error(429), api_error(503), response([1.0] * DIMENSIONS)])
    sleeps: list[float] = []

    vectors = gemini(stub, sleeps).embed_documents(["a"])

    assert len(stub.calls) == 3
    assert sleeps == [RETRY_BASE_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * RETRY_DELAY_FACTOR]
    assert len(vectors) == 1


def test_retries_network_errors() -> None:
    stub = StubGenai([httpx.ConnectError("reset"), response([1.0] * DIMENSIONS)])

    assert len(gemini(stub).embed_documents(["a"])) == 1


def test_gives_up_after_the_last_attempt_with_a_retryable_error() -> None:
    stub = StubGenai([api_error(429)] * RETRY_ATTEMPTS)
    sleeps: list[float] = []

    with pytest.raises(EmbeddingError) as raised:
        gemini(stub, sleeps).embed_documents(["a"])

    assert raised.value.retryable
    assert len(stub.calls) == RETRY_ATTEMPTS
    assert len(sleeps) == RETRY_ATTEMPTS - 1


def test_client_errors_are_not_retried_and_are_marked_non_retryable() -> None:
    stub = StubGenai([api_error(400)])

    with pytest.raises(EmbeddingError) as raised:
        gemini(stub).embed_documents(["a"])

    assert not raised.value.retryable
    assert len(stub.calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        response([1.0] * DIMENSIONS, [1.0] * DIMENSIONS),
        response([1.0] * (DIMENSIONS - 1)),
        SimpleNamespace(embeddings=None),
        response([0.0] * DIMENSIONS),
    ],
)
def test_malformed_responses_are_rejected(bad: object) -> None:
    with pytest.raises(EmbeddingError) as raised:
        gemini(StubGenai([bad])).embed_documents(["a"])

    assert raised.value.retryable


def test_requests_are_paced_to_the_per_minute_limit() -> None:
    stub = StubGenai([response([1.0] * DIMENSIONS)] * 2)
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = GeminiEmbeddingClient(
        SecretStr("k"),
        "gemini-embedding-001",
        DIMENSIONS,
        requests_per_minute=30,
        client=stub,  # type: ignore[arg-type]
        sleep=sleep,
        clock=lambda: now[0],
    )

    client.embed_documents(["a"])
    client.embed_documents(["b"])

    assert sleeps == [pytest.approx(2.0)]


def test_identity_comes_from_the_constructor() -> None:
    client = gemini(StubGenai([]), model_version="7")

    assert (client.model_name, client.model_version, client.dimensions) == (
        "gemini-embedding-001",
        "7",
        DIMENSIONS,
    )


def test_gemini_embedding_2_is_refused() -> None:
    with pytest.raises(ValueError, match="not supported"):
        GeminiEmbeddingClient(
            SecretStr("k"),
            "gemini-embedding-2",
            DIMENSIONS,
            client=StubGenai([]),  # type: ignore[arg-type]
        )
