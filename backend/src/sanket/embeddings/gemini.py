"""Gemini embeddings through google-genai.

Model: `gemini-embedding-001` (text only, up to 2048 input tokens, default 3072 dimensions,
any size from 128 to 3072 through `output_dimensionality`). Checked against the Gemini API
embeddings documentation on 2026-11-17:

- Only the full 3072 dimensions come back normalised; smaller sizes must be scaled to unit
  length by the caller, which this client does for every size.
- `task_type` tunes the vector: RETRIEVAL_DOCUMENT for stored text, RETRIEVAL_QUERY for the
  search query.
- `gemini-embedding-2` is a different design (no `task_type`, task given as a text prefix,
  several inputs in one call may be merged into one multimodal embedding), so it is refused
  here. Moving to it is a new client plus a new `model_version` (docs/indexing.md).

Requests are paced to a requests-per-minute limit and retried with backoff on quota (429),
server (5xx) and network errors; other 4xx errors are not retried.
"""

import logging
import time
from collections.abc import Callable, Sequence

import httpx
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from sanket.embeddings.client import EmbeddingError, check_vectors, l2_normalise

logger = logging.getLogger(__name__)

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"
# One embed_content call accepts at most this many texts (batchEmbedContents limit).
MAX_TEXTS_PER_REQUEST = 100
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_DELAY_FACTOR = 4.0
REQUEST_TIMEOUT_MS = 60_000
SECONDS_PER_MINUTE = 60.0
MAX_ERROR_CHARS = 300
UNSUPPORTED_MODEL_MARKER = "embedding-2"


class GeminiEmbeddingClient:
    def __init__(
        self,
        api_key: SecretStr,
        model_name: str,
        dimensions: int,
        model_version: str = "1",
        requests_per_minute: int | None = None,
        client: genai.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        retry_attempts: int = RETRY_ATTEMPTS,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
    ) -> None:
        if UNSUPPORTED_MODEL_MARKER in model_name:
            raise ValueError(f"{model_name} is not supported: see the module docstring")
        self.model_name = model_name
        self.model_version = model_version
        self.dimensions = dimensions
        self._client = client or genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=timeout_ms),
        )
        # A search request wants to fail fast, the indexing worker wants to be patient.
        self._retry_attempts = retry_attempts
        self._min_interval = SECONDS_PER_MINUTE / requests_per_minute if requests_per_minute else 0
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS_PER_REQUEST):
            chunk = list(texts[start : start + MAX_TEXTS_PER_REQUEST])
            vectors.extend(self._embed(chunk, TASK_DOCUMENT))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], TASK_QUERY)[0]

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        response = self._request_with_retry(texts, task_type)
        raw = [list(item.values or []) for item in response.embeddings or []]
        vectors = check_vectors(raw, len(texts), self.dimensions)
        return [l2_normalise(vector) for vector in vectors]

    def _request_with_retry(self, texts: list[str], task_type: str) -> types.EmbedContentResponse:
        delay = RETRY_BASE_DELAY_SECONDS
        for attempt in range(1, self._retry_attempts + 1):
            self._pace()
            try:
                return self._client.models.embed_content(
                    model=self.model_name,
                    contents=texts,
                    config=types.EmbedContentConfig(
                        task_type=task_type, output_dimensionality=self.dimensions
                    ),
                )
            except errors.APIError as error:
                if error.code not in RETRY_STATUS_CODES:
                    raise _to_error(error, retryable=False) from error
                failure = _to_error(error, retryable=True)
            except httpx.HTTPError as error:
                failure = _to_error(error, retryable=True)
            if attempt == self._retry_attempts:
                raise failure
            logger.warning(
                "Embedding request failed (attempt %d of %d), retrying in %.0fs: %s",
                attempt,
                self._retry_attempts,
                delay,
                failure,
            )
            self._sleep(delay)
            delay *= RETRY_DELAY_FACTOR
        raise AssertionError("unreachable")  # pragma: no cover


def _to_error(error: Exception, *, retryable: bool) -> EmbeddingError:
    message = str(error)[:MAX_ERROR_CHARS]
    return EmbeddingError(f"{type(error).__name__}: {message}", retryable=retryable)
