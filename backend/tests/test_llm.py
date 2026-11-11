from sanket.extraction import extract
from sanket.extraction.llm import LlmResponse


class InvalidJsonClient:
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system_prompt, messages, response_schema) -> LlmResponse:
        self.calls += 1
        return LlmResponse(text="not valid json")


def test_extract_fails_after_all_repairs_fail() -> None:
    client = InvalidJsonClient()

    result = extract.extract(client, "any posting")

    assert not result.ok
    assert result.data is None
    assert client.calls == extract.MAX_REPAIR_ATTEMPTS + 1
