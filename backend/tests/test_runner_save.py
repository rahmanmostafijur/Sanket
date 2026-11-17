from dataclasses import replace

from sqlalchemy import Engine

from sanket.extraction.extract import ExtractionResult
from sanket.extraction.runner import STATUS_FAILED, STATUS_OK, find_pending, save_extraction
from sanket.extraction.schema import JobExtraction
from tests.factories import (
    CFG,
    add_extraction,
    add_posting,
    count_extractions,
    get_extraction,
    require_extraction,
    set_content_hash,
)
from tests.test_extraction_schema import valid_data


def ok_result(title: str = "Backend Engineer", input_tokens: int = 10, output_tokens: int = 5):
    data = JobExtraction.model_validate(dict(valid_data(), title=title))
    return ExtractionResult(data, None, 1, input_tokens, output_tokens)


def failed_result(error: str = "failed validation after 2 repairs: boom"):
    return ExtractionResult(None, error, 3, 30, 9)


def save(engine: Engine, posting_id: int, content_hash: str, result, cfg=CFG) -> bool:
    with engine.begin() as conn:
        return save_extraction(conn, posting_id, content_hash, cfg, result)


def test_ok_result_is_stored_with_data_and_usage(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")

    save(clean_db, posting_id, "h1", ok_result(input_tokens=11, output_tokens=7))

    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_OK
    assert row.data["title"] == "Backend Engineer"
    assert row.content_hash == "h1"
    assert row.model == CFG.model
    assert (row.attempts, row.input_tokens, row.output_tokens) == (1, 11, 7)
    assert row.last_error is None


def test_failed_result_stores_the_error_and_sql_null_data(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")

    save(clean_db, posting_id, "h1", failed_result("bad json"))

    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_FAILED
    assert row.last_error == "bad json"
    assert row.data_is_sql_null


def test_first_insert_for_a_stale_hash_is_not_stored(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    set_content_hash(clean_db, posting_id, "h2")

    written = save(clean_db, posting_id, "h1", ok_result())

    assert written is False
    assert get_extraction(clean_db, posting_id) is None
    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_first_insert_of_a_failure_for_a_stale_hash_is_not_stored(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    set_content_hash(clean_db, posting_id, "h2")

    written = save(clean_db, posting_id, "h1", failed_result())

    assert written is False
    assert count_extractions(clean_db) == 0


def test_save_reports_whether_a_row_was_written(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")

    first = save(clean_db, posting_id, "h1", ok_result())
    replaced = save(clean_db, posting_id, "h1", ok_result(title="Second"))
    blocked_failure = save(clean_db, posting_id, "h1", failed_result())

    assert (first, replaced, blocked_failure) == (True, True, False)


def test_stale_result_does_not_replace_an_existing_row(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h2")
    add_extraction(clean_db, posting_id, status=STATUS_OK, content_hash="h2")

    save(clean_db, posting_id, "h1", ok_result(title="Stale Writer"))

    row = require_extraction(clean_db, posting_id)
    assert row.content_hash == "h2"
    assert row.data["title"] == "Backend Engineer"
    assert row.attempts == 1


def test_failure_never_replaces_an_ok_result_for_the_same_hash(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    save(clean_db, posting_id, "h1", ok_result(title="Kept"))

    save(clean_db, posting_id, "h1", failed_result())

    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_OK
    assert row.data["title"] == "Kept"
    assert row.last_error is None
    assert row.attempts == 1
    assert find_pending(CFG, 10, clean_db) == []


def test_later_ok_result_replaces_an_earlier_ok_result_for_the_same_hash(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    save(clean_db, posting_id, "h1", ok_result(title="First", input_tokens=1, output_tokens=1))

    save(clean_db, posting_id, "h1", ok_result(title="Second", input_tokens=2, output_tokens=3))

    row = require_extraction(clean_db, posting_id)
    assert row.data["title"] == "Second"
    assert (row.input_tokens, row.output_tokens) == (2, 3)
    assert row.attempts == 2
    assert count_extractions(clean_db) == 1


def test_ok_result_replaces_a_failure_for_the_same_hash(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    add_extraction(clean_db, posting_id, status=STATUS_FAILED, content_hash="h1", attempts=2)

    save(clean_db, posting_id, "h1", ok_result())

    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_OK
    assert row.data["title"] == "Backend Engineer"
    assert row.last_error is None
    assert not row.data_is_sql_null
    assert row.attempts == 3


def test_repeated_failures_count_attempts_until_the_posting_is_given_up(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")

    for expected_attempts in range(1, CFG.max_attempts + 1):
        assert find_pending(CFG, 10, clean_db) == [posting_id]
        save(clean_db, posting_id, "h1", failed_result())
        assert require_extraction(clean_db, posting_id).attempts == expected_attempts

    assert find_pending(CFG, 10, clean_db) == []


def test_changed_content_restarts_the_attempt_count(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    add_extraction(clean_db, posting_id, status=STATUS_FAILED, content_hash="h1", attempts=2)
    set_content_hash(clean_db, posting_id, "h2")

    save(clean_db, posting_id, "h2", failed_result())

    row = require_extraction(clean_db, posting_id)
    assert row.content_hash == "h2"
    assert row.attempts == 1


def test_ok_result_for_new_content_replaces_the_ok_result_for_old_content(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    save(clean_db, posting_id, "h1", ok_result(title="Old"))
    set_content_hash(clean_db, posting_id, "h2")

    save(clean_db, posting_id, "h2", ok_result(title="New"))

    row = require_extraction(clean_db, posting_id)
    assert row.data["title"] == "New"
    assert row.content_hash == "h2"
    assert row.attempts == 1


def test_failure_for_new_content_replaces_an_ok_result_for_old_content(clean_db) -> None:
    """The guard only protects an ok result for the same hash; old content is out of date."""
    posting_id = add_posting(clean_db, content_hash="h1")
    save(clean_db, posting_id, "h1", ok_result())
    set_content_hash(clean_db, posting_id, "h2")

    save(clean_db, posting_id, "h2", failed_result())

    row = require_extraction(clean_db, posting_id)
    assert row.status == STATUS_FAILED
    assert row.content_hash == "h2"
    assert row.data_is_sql_null


def test_each_schema_and_prompt_version_gets_its_own_row(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    save(clean_db, posting_id, "h1", ok_result(title="v-current"))
    next_cfg = replace(CFG, prompt_version=CFG.prompt_version + 1)

    save(clean_db, posting_id, "h1", ok_result(title="v-next"), cfg=next_cfg)

    assert count_extractions(clean_db) == 2
    assert require_extraction(clean_db, posting_id).data["title"] == "v-current"
    next_row = require_extraction(clean_db, posting_id, prompt_version=next_cfg.prompt_version)
    assert next_row.data["title"] == "v-next"
