from dataclasses import replace

from sanket.extraction.extract import MAX_REPAIR_ATTEMPTS
from sanket.extraction.llm import LlmError, LlmResponse
from sanket.extraction.runner import (
    MAX_CONSECUTIVE_PROVIDER_ERRORS,
    STATUS_FAILED,
    STATUS_OK,
    Outcome,
    extract_posting,
    find_pending,
    run_batch,
)
from tests.factories import (
    CFG,
    add_extraction,
    add_posting,
    count_extractions,
    require_extraction,
    set_content_hash,
)
from tests.test_llm import ScriptedClient, valid_response

BAD = LlmResponse("not json")
CALLS_PER_FAILED_POSTING = MAX_REPAIR_ATTEMPTS + 1


class RacingClient(ScriptedClient):
    """Runs a callback during the first model call, like a concurrent writer."""

    def __init__(self, responses, during_call) -> None:
        super().__init__(responses)
        self._during_call = during_call

    def generate(self, system_prompt, messages, response_schema) -> LlmResponse:
        if self.calls == 0:
            self._during_call()
        return super().generate(system_prompt, messages, response_schema)


def quota_error() -> LlmError:
    return LlmError("quota exceeded")


def test_extract_posting_stores_an_ok_result(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    client = ScriptedClient([valid_response(11, 7)])

    outcome = extract_posting(posting_id, client, CFG, clean_db)

    assert outcome is Outcome.OK
    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_OK
    assert row.content_hash == "h1"
    assert row.model == CFG.model
    assert (row.attempts, row.input_tokens, row.output_tokens) == (1, 11, 7)


def test_extract_posting_sends_the_cleaned_posting_text(clean_db) -> None:
    posting_id = add_posting(
        clean_db,
        title="Backend Engineer",
        company="Acme",
        location="Berlin",
        salary_text="50000-80000 USD per year",
        description="<p>Build <b>APIs</b>.</p>",
    )
    client = ScriptedClient([valid_response()])

    extract_posting(posting_id, client, CFG, clean_db)

    (message,) = client.conversations[0]
    assert message.role == "user"
    for expected in (
        "Title: Backend Engineer",
        "Company: Acme",
        "Location: Berlin",
        "Salary: 50000-80000 USD per year",
        "Build APIs.",
    ):
        assert expected in message.text
    assert "<p>" not in message.text


def test_extract_posting_truncates_long_descriptions(clean_db) -> None:
    posting_id = add_posting(clean_db, description="x" * 500)
    client = ScriptedClient([valid_response()])

    extract_posting(posting_id, client, replace(CFG, max_description_chars=50), clean_db)

    assert "[description truncated]" in client.conversations[0][0].text
    assert "x" * 51 not in client.conversations[0][0].text


def test_extract_posting_skips_an_already_extracted_posting(clean_db) -> None:
    posting_id = add_posting(clean_db)
    client = ScriptedClient([valid_response()])
    assert extract_posting(posting_id, client, CFG, clean_db) is Outcome.OK

    outcome = extract_posting(posting_id, client, CFG, clean_db)

    assert outcome is Outcome.SKIPPED
    assert client.calls == 1


def test_extract_posting_skips_unknown_ids_and_excluded_sources(clean_db) -> None:
    excluded = add_posting(clean_db, source="remoteok")
    cfg = replace(CFG, excluded_sources=("remoteok",))
    client = ScriptedClient([])

    assert extract_posting(999_999, client, cfg, clean_db) is Outcome.SKIPPED
    assert extract_posting(excluded, client, cfg, clean_db) is Outcome.SKIPPED
    assert client.calls == 0
    assert count_extractions(clean_db) == 0


def test_extract_posting_stores_a_failure_after_repairs_run_out(clean_db) -> None:
    posting_id = add_posting(clean_db)
    client = ScriptedClient([BAD] * CALLS_PER_FAILED_POSTING)

    outcome = extract_posting(posting_id, client, CFG, clean_db)

    assert outcome is Outcome.FAILED
    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_FAILED
    assert "failed validation" in row.last_error
    assert row.data_is_sql_null
    assert row.attempts == 1
    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_posting_is_given_up_after_max_attempts_failed_runs(clean_db) -> None:
    posting_id = add_posting(clean_db)
    client = ScriptedClient([BAD] * CALLS_PER_FAILED_POSTING * CFG.max_attempts)

    outcomes = [extract_posting(posting_id, client, CFG, clean_db) for _ in range(CFG.max_attempts)]
    after = extract_posting(posting_id, client, CFG, clean_db)

    assert outcomes == [Outcome.FAILED] * CFG.max_attempts
    assert after is Outcome.SKIPPED
    assert require_extraction(clean_db, posting_id).attempts == CFG.max_attempts


def test_provider_error_stores_nothing_and_keeps_the_posting_pending(clean_db) -> None:
    posting_id = add_posting(clean_db)
    client = ScriptedClient([quota_error()])

    outcome = extract_posting(posting_id, client, CFG, clean_db)

    assert outcome is Outcome.PROVIDER_ERROR
    assert count_extractions(clean_db) == 0
    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_posting_changed_during_the_call_is_extracted_again_on_the_next_run(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    racing = RacingClient(
        [valid_response()], during_call=lambda: set_content_hash(clean_db, posting_id, "h2")
    )

    outcome = extract_posting(posting_id, racing, CFG, clean_db)

    assert outcome is Outcome.SKIPPED
    assert count_extractions(clean_db) == 0
    assert find_pending(CFG, 10, clean_db) == [posting_id]
    retry = ScriptedClient([valid_response()])
    assert extract_posting(posting_id, retry, CFG, clean_db) is Outcome.OK
    assert require_extraction(clean_db, posting_id).content_hash == "h2"
    assert find_pending(CFG, 10, clean_db) == []


def test_ok_result_survives_a_concurrent_failing_worker(clean_db) -> None:
    """A slower duplicate job that fails must not erase the ok result already stored."""
    posting_id = add_posting(clean_db, content_hash="h1")
    client = RacingClient(
        [BAD] * CALLS_PER_FAILED_POSTING,
        during_call=lambda: add_extraction(
            clean_db, posting_id, status=STATUS_OK, content_hash="h1"
        ),
    )

    outcome = extract_posting(posting_id, client, CFG, clean_db)

    assert outcome is Outcome.SKIPPED
    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_OK
    assert row.last_error is None
    assert row.attempts == 1


def test_run_batch_extracts_only_pending_postings(clean_db) -> None:
    add_posting(clean_db)
    add_posting(clean_db)
    done = add_posting(clean_db)
    add_extraction(clean_db, done)
    client = ScriptedClient([valid_response()] * 2)

    counts = run_batch(client, CFG, 10, clean_db).counts

    assert dict(counts) == {Outcome.OK: 2}
    assert client.calls == 2
    assert count_extractions(clean_db) == 3


def test_run_batch_reports_each_outcome(clean_db) -> None:
    add_posting(clean_db)  # processed last: provider error
    add_posting(clean_db)  # processed second: validation failure
    add_posting(clean_db)  # processed first: ok
    script: list[LlmResponse | Exception] = [
        valid_response(),
        *[BAD] * CALLS_PER_FAILED_POSTING,
        quota_error(),
    ]
    client = ScriptedClient(script)

    counts = run_batch(client, CFG, 10, clean_db).counts

    assert dict(counts) == {Outcome.OK: 1, Outcome.FAILED: 1, Outcome.PROVIDER_ERROR: 1}


def test_run_batch_honours_the_limit_and_takes_newest_first(clean_db) -> None:
    ids = [add_posting(clean_db) for _ in range(4)]
    client = ScriptedClient([valid_response()] * 2)

    counts = run_batch(client, CFG, 2, clean_db).counts

    assert dict(counts) == {Outcome.OK: 2}
    assert find_pending(CFG, 10, clean_db) == [ids[1], ids[0]]


def test_run_batch_is_a_no_op_when_nothing_is_pending(clean_db) -> None:
    client = ScriptedClient([])

    assert run_batch(client, CFG, 10, clean_db).counts == {}
    assert client.calls == 0


def test_run_batch_twice_does_not_extract_again(clean_db) -> None:
    add_posting(clean_db)
    client = ScriptedClient([valid_response()])
    run_batch(client, CFG, 10, clean_db)

    second = run_batch(client, CFG, 10, clean_db).counts

    assert second == {}
    assert client.calls == 1


def test_run_batch_stops_after_consecutive_provider_errors(clean_db) -> None:
    for _ in range(MAX_CONSECUTIVE_PROVIDER_ERRORS + 2):
        add_posting(clean_db)
    client = ScriptedClient([quota_error()] * (MAX_CONSECUTIVE_PROVIDER_ERRORS + 2))

    counts = run_batch(client, CFG, 100, clean_db).counts

    assert dict(counts) == {Outcome.PROVIDER_ERROR: MAX_CONSECUTIVE_PROVIDER_ERRORS}
    assert client.calls == MAX_CONSECUTIVE_PROVIDER_ERRORS
    assert count_extractions(clean_db) == 0


def test_a_success_resets_the_consecutive_provider_error_count(clean_db) -> None:
    for _ in range(5):
        add_posting(clean_db)
    script: list[LlmResponse | Exception] = [
        quota_error(),
        quota_error(),
        valid_response(),
        quota_error(),
        quota_error(),
    ]
    client = ScriptedClient(script)

    counts = run_batch(client, CFG, 100, clean_db).counts

    assert client.calls == 5
    assert dict(counts) == {Outcome.PROVIDER_ERROR: 4, Outcome.OK: 1}
