import pytest

from sanket.extraction import llm


def test_extract_raises_after_all_repairs_fail(monkeypatch):
    calls = []

    def fake_generate(client, contents):
        calls.append(1)
        return "not valid json"

    monkeypatch.setattr(llm, "_client", lambda: None)
    monkeypatch.setattr(llm, "_generate", fake_generate)

    with pytest.raises(llm.ExtractionError):
        llm.extract("any posting")

    assert len(calls) == llm.MAX_REPAIR_ATTEMPTS + 1
