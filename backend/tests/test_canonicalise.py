from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import Engine, func, select

from sanket.canonical.fingerprint import fingerprint
from sanket.canonical.jobs import UpsertedJob, upsert_jobs
from sanket.canonical.plan import JobSeed
from sanket.canonical.service import CanonicaliseSummary, canonicalise, canonicalise_postings
from sanket.canonicalise import parse_args
from sanket.models import Job, Posting
from sanket.sources.base import NormalizedPosting
from sanket.storage import save_postings, to_row
from tests.canonical_helpers import (
    add_posting,
    all_jobs,
    at,
    get_job,
    job_of,
    posting_links,
    remove_posting,
    set_posting,
)


def run(engine: Engine, batch_size: int = 500) -> CanonicaliseSummary:
    return canonicalise(engine, batch_size=batch_size, apply=True)


def count_rows(engine: Engine, model: type) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(model)).scalar_one()


def test_the_same_job_from_several_sources_becomes_one_job(clean_db: Engine) -> None:
    a = add_posting(
        clean_db, source="remoteok", title="Backend Engineer (m/f/d)", company="Acme Inc."
    )
    b = add_posting(clean_db, source="greenhouse", title="backend engineer", company="ACME")
    c = add_posting(clean_db, source="lever", title="Backend  Engineer - REQ-12345", company="Acme")

    summary = run(clean_db)

    assert (summary.scanned, summary.linked, summary.jobs_created) == (3, 3, 1)
    assert job_of(clean_db, a) == job_of(clean_db, b) == job_of(clean_db, c) is not None
    (job,) = all_jobs(clean_db)
    assert job.posting_count == 3
    assert job.fingerprint == fingerprint(
        title="Backend Engineer", company="Acme", location="Berlin"
    )


def test_different_jobs_get_different_jobs(clean_db: Engine) -> None:
    add_posting(clean_db, title="Backend Engineer", company="Acme")
    add_posting(clean_db, title="Frontend Engineer", company="Acme")
    add_posting(clean_db, title="Backend Engineer", company="Globex")
    add_posting(clean_db, title="Backend Engineer", company="Acme", location="Munich")

    summary = run(clean_db)

    assert summary.jobs_created == 4
    assert len({job.id for job in all_jobs(clean_db)}) == 4
    assert {job.posting_count for job in all_jobs(clean_db)} == {1}


def test_second_run_changes_nothing(clean_db: Engine) -> None:
    add_posting(clean_db, source="remoteok", title="Backend Engineer", company="Acme")
    add_posting(clean_db, source="lever", title="Backend Engineer", company="Acme Inc")
    add_posting(clean_db, title="Data Analyst", company="Globex")
    add_posting(clean_db, title=None)
    run(clean_db)
    jobs_before = all_jobs(clean_db)
    links_before = posting_links(clean_db)

    second = run(clean_db)

    assert second.changes == 0
    assert second == CanonicaliseSummary(scanned=4, unchanged=3, no_fingerprint=1, applied=True)
    assert all_jobs(clean_db) == jobs_before
    assert posting_links(clean_db) == links_before


def test_postings_without_title_or_company_are_skipped_and_counted(clean_db: Engine) -> None:
    no_title = add_posting(clean_db, title=None)
    blank_company = add_posting(clean_db, company="   ")
    placeholder = add_posting(clean_db, company="Confidential")
    good = add_posting(clean_db)

    summary = run(clean_db)

    assert summary.no_fingerprint == 3
    assert summary.linked == 1
    assert [job_of(clean_db, pid) for pid in (no_title, blank_company, placeholder)] == [None] * 3
    assert job_of(clean_db, good) is not None
    assert count_rows(clean_db, Job) == 1


def test_a_posting_that_loses_its_title_is_detached_and_its_job_keeps_a_row(
    clean_db: Engine,
) -> None:
    posting_id = add_posting(clean_db)
    run(clean_db)
    job_id = job_of(clean_db, posting_id)
    assert job_id is not None
    set_posting(clean_db, posting_id, title=None)

    summary = run(clean_db)

    assert (summary.unlinked, summary.no_fingerprint) == (1, 1)
    assert job_of(clean_db, posting_id) is None
    job = get_job(clean_db, job_id)
    assert job.posting_count == 0
    assert job.representative_posting_id is None


def test_dry_run_writes_nothing_and_predicts_the_apply_run(clean_db: Engine) -> None:
    add_posting(clean_db, source="remoteok", title="Backend Engineer", company="Acme")
    add_posting(clean_db, source="lever", title="Backend Engineer", company="Acme Inc")
    add_posting(clean_db, title="Data Analyst", company="Globex")
    add_posting(clean_db, title=None)

    dry = canonicalise(clean_db, batch_size=2)

    assert dry.applied is False
    assert count_rows(clean_db, Job) == 0
    assert set(posting_links(clean_db).values()) == {None}
    applied = canonicalise(clean_db, batch_size=2, apply=True)
    assert replace(dry, applied=True) == applied
    assert (applied.jobs_created, applied.jobs_refreshed) == (2, 2)


def test_dry_run_after_apply_reports_nothing_to_do(clean_db: Engine) -> None:
    add_posting(clean_db)
    run(clean_db)

    dry = canonicalise(clean_db)

    assert dry.changes == 0
    assert dry.unchanged == 1


def test_dry_run_does_not_use_up_job_ids(clean_db: Engine) -> None:
    add_posting(clean_db)
    canonicalise(clean_db)
    run(clean_db)

    assert [job.id for job in all_jobs(clean_db)] == [1]


def test_aggregates_cover_all_member_postings(clean_db: Engine) -> None:
    add_posting(clean_db, source="a", first_seen=at(3), last_seen=at(5))
    add_posting(clean_db, source="b", first_seen=at(1), last_seen=at(4))
    add_posting(clean_db, source="c", first_seen=at(2), last_seen=at(9))

    run(clean_db)

    (job,) = all_jobs(clean_db)
    assert job.posting_count == 3
    assert job.first_seen_at == at(1)
    assert job.last_seen_at == at(9)


def test_representative_prefers_a_description_then_recency_then_lowest_id(
    clean_db: Engine,
) -> None:
    old_with_text = add_posting(clean_db, title="Backend Engineer", last_seen=at(1))
    newer_blank = add_posting(clean_db, title="BACKEND ENGINEER", description="  ", last_seen=at(9))
    newer_with_text = add_posting(clean_db, title="backend engineer", last_seen=at(5))
    same_time_later_id = add_posting(clean_db, title="backend  engineer", last_seen=at(5))

    run(clean_db)

    (job,) = all_jobs(clean_db)
    assert job.representative_posting_id == newer_with_text
    assert job.title == "backend engineer"
    assert newer_blank != job.representative_posting_id
    assert old_with_text != job.representative_posting_id
    assert same_time_later_id != job.representative_posting_id


def test_representative_without_any_description_is_the_most_recent(clean_db: Engine) -> None:
    add_posting(clean_db, description=None, last_seen=at(1))
    recent = add_posting(clean_db, description=None, last_seen=at(3))

    run(clean_db)

    assert all_jobs(clean_db)[0].representative_posting_id == recent


def test_display_fields_come_from_the_representative(clean_db: Engine) -> None:
    add_posting(
        clean_db, title="Senior Python Developer (m/f/d)", company="Acme GmbH", location="Berlin"
    )

    run(clean_db)

    (job,) = all_jobs(clean_db)
    assert (job.title, job.company, job.location) == (
        "Senior Python Developer (m/f/d)",
        "Acme GmbH",
        "Berlin",
    )


def test_a_posting_moves_to_another_job_when_its_title_changes(clean_db: Engine) -> None:
    stays = add_posting(clean_db, source="lever", title="Backend Engineer", last_seen=at(1))
    moves = add_posting(clean_db, source="remoteok", title="Backend Engineer", last_seen=at(5))
    run(clean_db)
    old_job = job_of(clean_db, moves)
    assert old_job is not None
    assert old_job == job_of(clean_db, stays)
    assert get_job(clean_db, old_job).representative_posting_id == moves

    set_posting(clean_db, moves, title="Staff Backend Engineer")
    summary = run(clean_db)

    new_job = job_of(clean_db, moves)
    assert new_job is not None
    assert (summary.moved, summary.jobs_created) == (1, 1)
    assert new_job != old_job
    assert job_of(clean_db, stays) == old_job
    old = get_job(clean_db, old_job)
    assert (old.posting_count, old.representative_posting_id) == (1, stays)
    assert (old.last_seen_at, old.title) == (at(1), "Backend Engineer")
    new = get_job(clean_db, new_job)
    assert (new.posting_count, new.representative_posting_id) == (1, moves)
    assert new.title == "Staff Backend Engineer"


def test_the_old_job_keeps_a_row_with_count_zero_when_its_last_posting_leaves(
    clean_db: Engine,
) -> None:
    posting_id = add_posting(clean_db, title="Backend Engineer", last_seen=at(2))
    run(clean_db)
    old_job = job_of(clean_db, posting_id)
    assert old_job is not None
    set_posting(clean_db, posting_id, title="Data Engineer")

    run(clean_db)

    old = get_job(clean_db, old_job)
    assert old.posting_count == 0
    assert old.representative_posting_id is None
    assert (old.title, old.company) == ("Backend Engineer", "Acme")
    assert old.last_seen_at == at(2)
    assert count_rows(clean_db, Job) == 2
    assert job_of(clean_db, posting_id) != old_job
    assert run(clean_db).changes == 0


def test_a_posting_moves_back_to_an_existing_empty_job(clean_db: Engine) -> None:
    posting_id = add_posting(clean_db, title="Backend Engineer")
    run(clean_db)
    first_job = job_of(clean_db, posting_id)
    assert first_job is not None
    set_posting(clean_db, posting_id, title="Data Engineer")
    run(clean_db)
    set_posting(clean_db, posting_id, title="Backend Engineer")

    summary = run(clean_db)

    assert summary.jobs_created == 0
    assert job_of(clean_db, posting_id) == first_job
    assert get_job(clean_db, first_job).posting_count == 1
    assert count_rows(clean_db, Job) == 2


def ingest_version(**overrides: object) -> NormalizedPosting:
    fields: dict[str, object] = {
        "source": "greenhouse",
        "source_id": "acme:1",
        "url": "https://example.com/jobs/1",
        "title": "Backend Developer",
        "raw": {"version": 1},
        "company": "Acme",
        "location": "Berlin",
        "description": "<p>Original description.</p>",
    }
    return NormalizedPosting(**{**fields, **overrides})  # type: ignore[arg-type]


def test_reingesting_keeps_the_job_and_a_changed_title_regroups_on_the_next_run(
    clean_db: Engine,
) -> None:
    save_postings([to_row(ingest_version())], clean_db)
    save_postings([to_row(ingest_version(source_id="acme:2", source="lever"))], clean_db)
    run(clean_db)
    links = posting_links(clean_db)
    job_a = next(iter(links.values()))
    assert job_a is not None
    assert set(links.values()) == {job_a}

    save_postings([to_row(ingest_version())], clean_db)
    assert posting_links(clean_db) == links

    changed = ingest_version(title="Principal Backend Developer", raw={"version": 2})
    save_postings([to_row(changed)], clean_db)
    assert posting_links(clean_db) == links
    summary = run(clean_db)

    moved_id = next(pid for pid in links if job_of(clean_db, pid) != job_a)
    job_b = job_of(clean_db, moved_id)
    assert job_b is not None
    assert (summary.moved, summary.unchanged, summary.jobs_created) == (1, 1, 1)
    assert get_job(clean_db, job_a).posting_count == 1
    assert get_job(clean_db, job_b).posting_count == 1
    assert get_job(clean_db, job_b).title == "Principal Backend Developer"


def test_reingest_that_moves_the_only_posting_leaves_job_a_with_count_zero(
    clean_db: Engine,
) -> None:
    save_postings([to_row(ingest_version())], clean_db)
    run(clean_db)
    with clean_db.connect() as conn:
        job_a = conn.execute(select(Posting.job_id)).scalar_one()
    assert job_a is not None

    save_postings([to_row(ingest_version(title="Staff Developer", raw={"v": 2}))], clean_db)
    run(clean_db)

    with clean_db.connect() as conn:
        job_b = conn.execute(select(Posting.job_id)).scalar_one()
    assert job_b is not None
    assert job_b != job_a
    assert get_job(clean_db, job_a).posting_count == 0
    assert get_job(clean_db, job_b).posting_count == 1
    assert count_rows(clean_db, Job) == 2


def test_resync_refreshes_seen_times_after_postings_are_seen_again(clean_db: Engine) -> None:
    a = add_posting(clean_db, source="a", last_seen=at(1))
    add_posting(clean_db, source="b", last_seen=at(2))
    run(clean_db)
    set_posting(clean_db, a, last_seen_at=at(8))

    dry = canonicalise(clean_db)
    summary = run(clean_db)

    assert dry.jobs_resynced == summary.jobs_resynced == 1
    assert (summary.linked, summary.moved) == (0, 0)
    assert all_jobs(clean_db)[0].last_seen_at == at(8)
    assert run(clean_db).changes == 0


def test_a_resynced_job_gets_its_representative_chosen_again(clean_db: Engine) -> None:
    first = add_posting(clean_db, source="a", last_seen=at(1))
    second = add_posting(clean_db, source="b", last_seen=at(2))
    run(clean_db)
    assert all_jobs(clean_db)[0].representative_posting_id == second

    set_posting(clean_db, first, last_seen_at=at(3))
    run(clean_db)

    assert all_jobs(clean_db)[0].representative_posting_id == first
    assert run(clean_db).changes == 0


def test_a_re_seen_posting_that_changes_no_aggregate_does_not_rewrite_the_job(
    clean_db: Engine,
) -> None:
    first = add_posting(clean_db, source="a", last_seen=at(1))
    add_posting(clean_db, source="b", last_seen=at(5))
    run(clean_db)
    before = all_jobs(clean_db)

    set_posting(clean_db, first, last_seen_at=at(4))
    summary = run(clean_db)

    assert summary.jobs_resynced == 0
    assert all_jobs(clean_db) == before


def test_resync_notices_a_deleted_posting(clean_db: Engine) -> None:
    keep = add_posting(clean_db, source="a")
    gone = add_posting(clean_db, source="b", last_seen=at(9))
    run(clean_db)
    remove_posting(clean_db, gone)

    summary = run(clean_db)

    assert summary.jobs_resynced == 1
    job = all_jobs(clean_db)[0]
    assert (job.posting_count, job.representative_posting_id) == (1, keep)


def test_batches_give_the_same_result_as_one_big_batch(clean_db: Engine) -> None:
    for number in range(7):
        add_posting(clean_db, source=f"s{number}", title=f"Engineer {number % 3}")
    add_posting(clean_db, title=None)

    summary = run(clean_db, batch_size=2)

    assert (summary.scanned, summary.linked, summary.no_fingerprint) == (8, 7, 1)
    assert summary.jobs_created == 3
    assert sorted(job.posting_count for job in all_jobs(clean_db)) == [2, 2, 3]
    assert run(clean_db, batch_size=3).changes == 0


def test_canonicalise_postings_handles_only_the_given_ids(clean_db: Engine) -> None:
    first = add_posting(clean_db, title="Backend Engineer")
    second = add_posting(clean_db, title="Backend Engineer", source="lever")
    other = add_posting(clean_db, title="Data Analyst")

    summary = canonicalise_postings([first, second, 9999], clean_db)

    assert (summary.scanned, summary.linked, summary.jobs_created) == (2, 2, 1)
    assert job_of(clean_db, first) == job_of(clean_db, second) is not None
    assert job_of(clean_db, other) is None
    assert summary.applied is True


def test_canonicalise_postings_is_idempotent_and_accepts_nothing(clean_db: Engine) -> None:
    first = add_posting(clean_db)
    canonicalise_postings([first, first], clean_db)

    again = canonicalise_postings([first], clean_db)

    assert again.changes == 0
    assert canonicalise_postings([], clean_db) == CanonicaliseSummary(applied=True)
    assert count_rows(clean_db, Job) == 1


def test_canonicalise_postings_joins_an_existing_job_and_updates_its_aggregates(
    clean_db: Engine,
) -> None:
    first = add_posting(clean_db, title="Backend Engineer", last_seen=at(1))
    run(clean_db)
    late = add_posting(clean_db, title="Backend Engineer", source="lever", last_seen=at(6))

    summary = canonicalise_postings([late], clean_db)

    assert (summary.linked, summary.jobs_created) == (1, 0)
    job = all_jobs(clean_db)[0]
    assert (job.posting_count, job.last_seen_at, job.representative_posting_id) == (2, at(6), late)
    assert job_of(clean_db, first) == job.id


def seed(fingerprint_value: str) -> JobSeed:
    return JobSeed(fingerprint_value, "Engineer", "Acme", None)


def test_upserting_the_same_fingerprint_twice_creates_one_job(clean_db: Engine) -> None:
    with clean_db.begin() as conn:
        first = upsert_jobs(conn, [seed("fp1:a")])
    with clean_db.begin() as conn:
        second = upsert_jobs(conn, [seed("fp1:a"), seed("fp1:a")])

    assert first["fp1:a"].created is True
    assert second["fp1:a"].created is False
    assert first["fp1:a"].id == second["fp1:a"].id
    assert count_rows(clean_db, Job) == 1


def upsert_in_new_transaction(engine: Engine, fingerprint_value: str) -> UpsertedJob:
    with engine.begin() as conn:
        return upsert_jobs(conn, [seed(fingerprint_value)])[fingerprint_value]


def test_a_concurrent_insert_of_the_same_fingerprint_waits_and_reuses_the_row(
    clean_db: Engine,
) -> None:
    with clean_db.connect() as first_conn, ThreadPoolExecutor(max_workers=1) as pool:
        with first_conn.begin():
            first = upsert_jobs(first_conn, [seed("fp1:race")])
            # The second transaction queues behind our uncommitted insert of the same key.
            pending = pool.submit(upsert_in_new_transaction, clean_db, "fp1:race")
        second = pending.result(timeout=30)

    assert second.id == first["fp1:race"].id
    assert second.created is False
    assert count_rows(clean_db, Job) == 1


def test_two_runs_at_the_same_time_do_not_create_duplicate_jobs(clean_db: Engine) -> None:
    for number in range(30):
        add_posting(clean_db, source=f"s{number}", title=f"Engineer {number % 5}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, clean_db, 10) for _ in range(2)]
        results = [future.result(timeout=60) for future in futures]

    jobs = all_jobs(clean_db)
    assert len(jobs) == 5
    assert len({job.fingerprint for job in jobs}) == 5
    assert sorted(job.posting_count for job in jobs) == [6] * 5
    assert sum(result.jobs_created for result in results) == 5
    assert None not in posting_links(clean_db).values()
    assert run(clean_db).changes == 0


def test_dry_run_is_the_default() -> None:
    assert parse_args([]).apply is False
    assert parse_args(["--dry-run"]).apply is False
    assert parse_args(["--apply"]).apply is True


def test_dry_run_and_apply_cannot_be_combined() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--apply"])


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "0"])


def test_summary_line_is_stable() -> None:
    summary = CanonicaliseSummary(
        scanned=5, linked=2, jobs_created=1, jobs_refreshed=1, applied=True
    )

    assert summary.line() == (
        "canonicalise mode=apply scanned=5 linked=2 moved=0 unlinked=0 unchanged=0 "
        "no_fingerprint=0 jobs_created=1 jobs_refreshed=1 jobs_resynced=0"
    )
