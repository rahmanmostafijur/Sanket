import json
from collections.abc import Sequence

from sanket.extraction import extract
from sanket.extraction.llm import ChatMessage, LlmResponse
from sanket.extraction.prompt import repair_message
from sanket.extraction.schema import WorkMode
from tests.test_extraction_schema import valid_data


class ScriptedClient:
    """Returns the given responses in order and records every conversation it receives.

    An Exception in the script is raised instead of returned, like a failing provider call."""

    model = "fake"

    def __init__(self, responses: Sequence[LlmResponse | Exception]) -> None:
        self._responses = list(responses)
        self.conversations: list[list[ChatMessage]] = []

    @property
    def calls(self) -> int:
        return len(self.conversations)

    def generate(self, system_prompt, messages, response_schema) -> LlmResponse:
        self.conversations.append(list(messages))
        item = self._responses[len(self.conversations) - 1]
        if isinstance(item, Exception):
            raise item
        return item


def valid_response(input_tokens: int = 0, output_tokens: int = 0) -> LlmResponse:
    return LlmResponse(json.dumps(valid_data()), input_tokens, output_tokens)


def test_extract_succeeds_on_first_try_without_repair() -> None:
    client = ScriptedClient([valid_response()])

    result = extract.extract(client, "any posting")

    assert result.ok
    assert result.error is None
    assert result.data is not None
    assert result.data.work_mode == WorkMode.REMOTE
    assert result.calls == 1
    assert client.calls == 1


def test_extract_repairs_invalid_output_then_succeeds() -> None:
    bad = dict(valid_data(), work_mode="work from home")
    client = ScriptedClient([LlmResponse(json.dumps(bad)), valid_response()])

    result = extract.extract(client, "any posting")

    assert result.ok
    assert result.calls == 2
    repair_turn = client.conversations[1]
    assert [m.role for m in repair_turn] == ["user", "assistant", "user"]
    assert repair_turn[1].text == json.dumps(bad)
    assert "work_mode" in repair_turn[2].text


def test_extract_treats_empty_response_as_repairable_error() -> None:
    client = ScriptedClient([LlmResponse(None), valid_response()])

    result = extract.extract(client, "any posting")

    assert result.ok
    assert result.calls == 2
    assert client.conversations[1][-1] == ChatMessage(
        "user", repair_message(extract.EMPTY_RESPONSE_ERROR)
    )


def test_extract_fails_after_all_repairs_fail() -> None:
    client = ScriptedClient([LlmResponse("not valid json")] * (extract.MAX_REPAIR_ATTEMPTS + 1))

    result = extract.extract(client, "any posting")

    assert not result.ok
    assert result.data is None
    assert result.calls == extract.MAX_REPAIR_ATTEMPTS + 1
    assert result.error is not None
    assert "failed validation after" in result.error


def test_extract_fails_when_every_response_is_empty() -> None:
    client = ScriptedClient([LlmResponse(None)] * (extract.MAX_REPAIR_ATTEMPTS + 1))

    result = extract.extract(client, "any posting")

    assert not result.ok
    assert result.error is not None
    assert extract.EMPTY_RESPONSE_ERROR in result.error


def test_extract_sums_token_usage_across_attempts() -> None:
    client = ScriptedClient([LlmResponse("nope", 10, 3), valid_response(20, 5)])

    result = extract.extract(client, "any posting")

    assert result.input_tokens == 30
    assert result.output_tokens == 8
