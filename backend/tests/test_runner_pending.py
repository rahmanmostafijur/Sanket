from dataclasses import replace

import pytest

from sanket.extraction.runner import STATUS_FAILED, STATUS_OK, find_pending
from tests.factories import CFG, add_extraction, add_posting, set_content_hash


def test_new_posting_is_pending(clean_db) -> None:
    posting_id = add_posting(clean_db)

    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_posting_with_current_ok_extraction_is_not_pending(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    add_extraction(clean_db, posting_id, status=STATUS_OK, content_hash="h1")

    assert find_pending(CFG, 10, clean_db) == []


def test_posting_whose_content_changed_is_pending_again(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    add_extraction(clean_db, posting_id, status=STATUS_OK, content_hash="h1")

    set_content_hash(clean_db, posting_id, "h2")

    assert find_pending(CFG, 10, clean_db) == [posting_id]


@pytest.mark.parametrize("version_field", ["schema_version", "prompt_version"])
def test_extraction_from_an_older_version_is_pending(clean_db, version_field: str) -> None:
    posting_id = add_posting(clean_db)
    add_extraction(
        clean_db,
        posting_id,
        **{version_field: getattr(CFG, version_field) - 1},
    )

    assert find_pending(CFG, 10, clean_db) == [posting_id]


@pytest.mark.parametrize("version_field", ["schema_version", "prompt_version"])
def test_bumping_a_version_makes_current_extractions_pending(clean_db, version_field) -> None:
    posting_id = add_posting(clean_db)
    add_extraction(clean_db, posting_id)
    assert find_pending(CFG, 10, clean_db) == []

    bumped = replace(CFG, **{version_field: getattr(CFG, version_field) + 1})

    assert find_pending(bumped, 10, clean_db) == [posting_id]


def test_failed_extraction_below_max_attempts_is_pending(clean_db) -> None:
    posting_id = add_posting(clean_db)
    add_extraction(clean_db, posting_id, status=STATUS_FAILED, attempts=CFG.max_attempts - 1)

    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_failed_extraction_at_max_attempts_is_not_pending(clean_db) -> None:
    posting_id = add_posting(clean_db)
    add_extraction(clean_db, posting_id, status=STATUS_FAILED, attempts=CFG.max_attempts)

    assert find_pending(CFG, 10, clean_db) == []


def test_exhausted_failure_is_pending_again_when_content_changes(clean_db) -> None:
    posting_id = add_posting(clean_db, content_hash="h1")
    add_extraction(
        clean_db, posting_id, status=STATUS_FAILED, content_hash="h1", attempts=CFG.max_attempts
    )

    set_content_hash(clean_db, posting_id, "h2")

    assert find_pending(CFG, 10, clean_db) == [posting_id]


def test_excluded_source_is_never_pending(clean_db) -> None:
    add_posting(clean_db, source="remoteok")
    kept = add_posting(clean_db, source="greenhouse")
    cfg = replace(CFG, excluded_sources=("remoteok",))

    assert find_pending(cfg, 10, clean_db) == [kept]


def test_pending_postings_come_newest_first_and_respect_the_limit(clean_db) -> None:
    ids = [add_posting(clean_db) for _ in range(4)]

    assert find_pending(CFG, 10, clean_db) == ids[::-1]
    assert find_pending(CFG, 2, clean_db) == ids[:1:-1]


def test_selects_exactly_the_postings_that_need_extraction(clean_db) -> None:
    new = add_posting(clean_db)

    done = add_posting(clean_db)
    add_extraction(clean_db, done)

    changed = add_posting(clean_db, content_hash="h2")
    add_extraction(clean_db, changed, content_hash="h1")

    old_schema = add_posting(clean_db)
    add_extraction(clean_db, old_schema, schema_version=CFG.schema_version - 1)

    old_prompt = add_posting(clean_db)
    add_extraction(clean_db, old_prompt, prompt_version=CFG.prompt_version - 1)

    retrying = add_posting(clean_db)
    add_extraction(clean_db, retrying, status=STATUS_FAILED, attempts=1)

    given_up = add_posting(clean_db)
    add_extraction(clean_db, given_up, status=STATUS_FAILED, attempts=CFG.max_attempts)

    pending = find_pending(CFG, 100, clean_db)

    assert set(pending) == {new, changed, old_schema, old_prompt, retrying}
    assert len(pending) == 5
