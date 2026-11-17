"""Provider-neutral LLM interface and the Gemini implementation."""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_STATUS_CODES = [429, 500, 502, 503, 504]
SECONDS_PER_MINUTE = 60.0
MAX_ERROR_CHARS = 300


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
            message = str(error)[:MAX_ERROR_CHARS]
            raise LlmError(f"{type(error).__name__}: {message}") from error
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
