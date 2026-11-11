"""Prompt -> model -> parse -> validate, with a bounded repair loop."""

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from sanket.extraction.llm import ChatMessage, LlmClient
from sanket.extraction.prompt import SYSTEM_PROMPT, repair_message
from sanket.extraction.schema import JobExtraction

MAX_REPAIR_ATTEMPTS = 2
RESPONSE_SCHEMA = JobExtraction.model_json_schema()
EMPTY_RESPONSE_ERROR = "model returned no text"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    """Validated data, or the last error once every repair attempt is used."""

    data: JobExtraction | None
    error: str | None
    calls: int
    input_tokens: int
    output_tokens: int

    @property
    def ok(self) -> bool:
        return self.data is not None


def format_errors(error: ValidationError) -> str:
    lines = []
    for err in error.errors(include_url=False, include_input=False):
        field = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"{field}: {err['msg']}")
    return "\n".join(lines)


def extract(client: LlmClient, posting_text: str) -> ExtractionResult:
    """Run the extraction. LlmError from the provider propagates to the caller."""
    messages = [ChatMessage("user", posting_text)]
    input_tokens = output_tokens = 0
    error = EMPTY_RESPONSE_ERROR
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
        response = client.generate(SYSTEM_PROMPT, messages, RESPONSE_SCHEMA)
        input_tokens += response.input_tokens
        output_tokens += response.output_tokens
        if response.text is None:
            error = EMPTY_RESPONSE_ERROR
            messages = [*messages, ChatMessage("user", repair_message(error))]
        else:
            try:
                data = JobExtraction.model_validate_json(response.text)
            except ValidationError as validation_error:
                error = format_errors(validation_error)
                messages = [
                    *messages,
                    ChatMessage("assistant", response.text),
                    ChatMessage("user", repair_message(error)),
                ]
            else:
                return ExtractionResult(data, None, attempt, input_tokens, output_tokens)
        logger.warning(
            "Extraction failed validation (attempt %d of %d): %s",
            attempt,
            MAX_REPAIR_ATTEMPTS + 1,
            error,
        )
    return ExtractionResult(
        None,
        f"failed validation after {MAX_REPAIR_ATTEMPTS} repairs: {error}",
        MAX_REPAIR_ATTEMPTS + 1,
        input_tokens,
        output_tokens,
    )
