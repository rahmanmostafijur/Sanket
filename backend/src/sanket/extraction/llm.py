"""Provider-neutral LLM interface and the Gemini implementation."""

import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
SECONDS_PER_MINUTE = 60.0
MAX_ERROR_CHARS = 300
HTTP_TOO_MANY_REQUESTS = 429
# Waits after a rate-limited call (on top of the SDK's own short retries): base * 2 ** n
# seconds, capped, with jitter, and never shorter than the wait the provider suggests.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF_BASE_SECONDS = 10.0
RATE_LIMIT_BACKOFF_MAX_SECONDS = 120.0


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class LlmResponse:
    text: str | None
    input_tokens: int = 0
    output_tokens: int = 0


class LlmError(Exception):
    """The provider call itself failed (network, quota, server error)."""


class LlmRateLimitError(LlmError):
    """The provider refused the call for quota (HTTP 429), after the SDK's own retries.

    `retry_after` is the wait the provider suggested, if any; `daily` is set when the
    exhausted quota is a per-day one, which waiting minutes cannot fix."""

    def __init__(self, message: str, retry_after: float | None = None, daily: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily


class LlmClient(Protocol):
    model: str

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict
    ) -> LlmResponse:
        """Return the model's JSON text for the conversation, constrained by the schema."""
        ...


class GeminiClient:
    """Gemini via google-genai, paced to stay under a requests-per-minute quota."""

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        requests_per_minute: int | None = None,
        client: genai.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self._client = client or genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=RETRY_ATTEMPTS, http_status_codes=RETRY_STATUS_CODES
                )
            ),
        )
        self._min_interval = SECONDS_PER_MINUTE / requests_per_minute if requests_per_minute else 0
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict
    ) -> LlmResponse:
        self._pace()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[_to_content(message) for message in messages],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_json_schema=response_schema,
                ),
            )
        except (errors.APIError, httpx.HTTPError) as error:
            message = f"{type(error).__name__}: {str(error)[:MAX_ERROR_CHARS]}"
            if isinstance(error, errors.APIError) and error.code == HTTP_TOO_MANY_REQUESTS:
                retry_after, daily = _quota_details(error.details)
                raise LlmRateLimitError(message, retry_after, daily) from error
            raise LlmError(message) from error
        usage = response.usage_metadata
        return LlmResponse(
            text=response.text,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(
                (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if usage
                else 0
            ),
        )


def _to_content(message: ChatMessage) -> types.Content:
    role = "model" if message.role == "assistant" else "user"
    return types.Content(role=role, parts=[types.Part(text=message.text)])


def _retry_delay(item: dict[str, Any]) -> float | None:
    """Seconds from a `google.rpc.RetryInfo` entry such as {"retryDelay": "37s"}."""
    delay = item.get("retryDelay")
    if not isinstance(delay, str) or not delay.endswith("s"):
        return None
    try:
        return float(delay[:-1])
    except ValueError:
        return None


def _is_daily(item: dict[str, Any]) -> bool:
    """Whether a `google.rpc.QuotaFailure` entry names a per-day quota."""
    violations = item.get("violations")
    if not isinstance(violations, list):
        return False
    return any(
        isinstance(violation, dict) and "PerDay" in str(violation.get("quotaId", ""))
        for violation in violations
    )


def _quota_details(body: object) -> tuple[float | None, bool]:
    """The suggested wait and whether a per-day quota ran out, from a 429 error body."""
    error = body.get("error", body) if isinstance(body, dict) else None
    items = error.get("details") if isinstance(error, dict) else None
    entries = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    delays = [delay for delay in map(_retry_delay, entries) if delay is not None]
    return (max(delays) if delays else None), any(map(_is_daily, entries))


def backoff_delay(
    retry: int,
    retry_after: float | None,
    rand: Callable[[float, float], float] = random.uniform,
) -> float:
    """Wait before retry number `retry` (from 0): exponential with jitter in its upper half,
    and at least the provider's suggestion (itself capped)."""
    ceiling = min(RATE_LIMIT_BACKOFF_MAX_SECONDS, RATE_LIMIT_BACKOFF_BASE_SECONDS * 2**retry)
    suggested = min(retry_after or 0.0, RATE_LIMIT_BACKOFF_MAX_SECONDS)
    return max(rand(ceiling / 2, ceiling), suggested)


class BackoffLlmClient:
    """A client that waits out rate limits instead of failing the call.

    A rate-limited call is retried after `backoff_delay`, up to `retries` times, then the
    error is raised. A per-day quota is not waited for: it is raised at once and
    `daily_quota_exhausted` is set. `rate_limited` and `backoffs` count what happened, for
    progress reports.
    """

    def __init__(
        self,
        inner: LlmClient,
        retries: int = RATE_LIMIT_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.model = inner.model
        self._inner = inner
        self._retries = retries
        self._sleep = sleep
        self._rand = rand
        self.rate_limited = 0
        self.backoffs = 0
        self.daily_quota_exhausted = False

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict
    ) -> LlmResponse:
        retry = 0
        while True:
            try:
                return self._inner.generate(system_prompt, messages, response_schema)
            except LlmRateLimitError as error:
                self.rate_limited += 1
                if error.daily:
                    self.daily_quota_exhausted = True
                    raise
                if retry >= self._retries:
                    raise
                delay = backoff_delay(retry, error.retry_after, self._rand)
                retry += 1
                self.backoffs += 1
                logger.warning(
                    "Rate limited by the provider; retrying in %.1fs (backoff %d of %d)",
                    delay,
                    retry,
                    self._retries,
                )
                self._sleep(delay)
