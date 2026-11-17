"""The profile side of matching: a saved or changed profile against recent jobs."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, delete, update

from sanket.matching.service import (
    SKIP_MISSING,
    SKIP_NOT_READY,
    MatchSummary,
    match_job,
    match_profile,
)
from sanket.models import EmbeddingStatus, Profile, ProfileEmbedding
from tests.index_helpers import set_posting_count
from tests.match_helpers import (
    OWNER,
    FailingNotifier,
    RecordingNotifier,
    add_profile,
    config,
    index_all,
    match_rows,
    seed_job,
)

LENIENT = config(min_cosine=-1.0, min_score=0.0)
SUMMARY = "backend engineer python postgresql apis"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
RECENT = NOW - timedelta(days=3)
OLD = NOW - timedelta(days=90)


def indexed_jobs(engine: Engine, **published: datetime) -> dict[str, int]:
    """Jobs by name, each published at the given time, all indexed."""
    jobs = {
        name: seed_job(engine, title=f"Backend Engineer {name}", published_at=when)
        for name, when in published.items()
    }
    index_all(engine)
    return jobs


def run(engine: Engine, profile_id: int, **kwargs: Any) -> MatchSummary:
    return match_profile(profile_id, LENIENT, now=NOW, db_engine=engine, **kwargs)


def statuses(engine: Engine) -> dict[int, str]:
    return {row["job_id"]: row["status"] for row in match_rows(engine)}


# --- what is matched --------------------------------------------------------------------------


def test_a_profile_is_matched_against_recent_jobs_and_announced_once(clean_db: Engine) -> None:
    jobs = indexed_jobs(clean_db, one=RECENT, two=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    notifier = RecordingNotifier()

    summary = run(clean_db, profile.id, notifier=notifier)

    assert summary == MatchSummary(evaluated=2, created=2)
    assert set(statuses(clean_db)) == set(jobs.values())
    assert sorted(r.job_id for r in notifier.records) == sorted(jobs.values())
    assert {r.owner_id for r in notifier.records} == {OWNER}
    assert all(r.profile_id == profile.id and not r.reactivated for r in notifier.records)
    assert all(row["notified_at"] is not None for row in match_rows(clean_db))


def test_running_again_is_a_no_op(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    notifier = RecordingNotifier()
    run(clean_db, profile.id, notifier=notifier)
    before = match_rows(clean_db)

    summary = run(clean_db, profile.id, notifier=notifier)

    assert summary == MatchSummary(evaluated=1)
    assert match_rows(clean_db) == before
    assert len(notifier.records) == 1


def test_only_jobs_seen_within_the_recent_window_are_matched(clean_db: Engine) -> None:
    jobs = indexed_jobs(clean_db, recent=RECENT, old=OLD)
    profile = add_profile(clean_db, summary=SUMMARY)

    summary = run(clean_db, profile.id)

    assert summary.created == 1
    assert set(statuses(clean_db)) == {jobs["recent"]}


def test_the_window_is_the_configured_number_of_days(clean_db: Engine) -> None:
    jobs = indexed_jobs(clean_db, recent=RECENT, old=OLD)
    profile = add_profile(clean_db, summary=SUMMARY)
    wide = config(recent_job_days=120, min_cosine=-1.0, min_score=0.0)

    match_profile(profile.id, wide, now=NOW, db_engine=clean_db)

    assert set(statuses(clean_db)) == set(jobs.values())


def test_jobs_per_profile_are_limited_to_the_nearest(clean_db: Engine) -> None:
    near = seed_job(clean_db, title="Backend Engineer", published_at=RECENT)
    seed_job(clean_db, title="Gardener Tomatoes Compost", published_at=RECENT)
    index_all(clean_db)
    profile = add_profile(clean_db, summary=SUMMARY)

    summary = match_profile(
        profile.id,
        config(max_jobs_per_profile=1, min_cosine=-1.0, min_score=0.0),
        now=NOW,
        db_engine=clean_db,
    )

    assert summary.created == 1
    assert set(statuses(clean_db)) == {near}


def test_the_default_thresholds_keep_an_unrelated_job_out(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary="gardening tomatoes greenhouse compost")

    summary = match_profile(profile.id, config(), now=NOW, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1)
    assert match_rows(clean_db) == []


# --- held matches are rescored ----------------------------------------------------------------


def test_a_job_outside_the_window_is_rescored_while_the_profile_holds_a_match_on_it(
    clean_db: Engine,
) -> None:
    jobs = indexed_jobs(clean_db, old=OLD)
    profile = add_profile(clean_db, summary=SUMMARY, work_modes=["remote"])
    match_job(jobs["old"], LENIENT, db_engine=clean_db)
    [held] = match_rows(clean_db)

    unchanged = run(clean_db, profile.id)

    assert unchanged == MatchSummary(evaluated=1)
    assert match_rows(clean_db) == [held]


def test_a_changed_profile_withdraws_a_held_match_it_no_longer_wants(clean_db: Engine) -> None:
    jobs = indexed_jobs(clean_db, old=OLD, recent=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY, work_modes=["remote"])
    run(clean_db, profile.id)
    match_job(jobs["old"], LENIENT, db_engine=clean_db)
    assert set(statuses(clean_db).values()) == {"active"}

    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == profile.id)
            .values(criteria={**profile.criteria, "work_modes": ["onsite"]}, content_hash="changed")
        )
    summary = run(clean_db, profile.id)

    assert summary == MatchSummary(evaluated=2, withdrawn=2, updated=0)
    assert set(statuses(clean_db).values()) == {"withdrawn"}


def test_a_held_match_on_a_job_that_died_is_withdrawn(clean_db: Engine) -> None:
    jobs = indexed_jobs(clean_db, one=RECENT, two=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    run(clean_db, profile.id)
    set_posting_count(clean_db, jobs["two"], 0)

    summary = run(clean_db, profile.id)

    assert summary.withdrawn == 1 and summary.created == 0
    assert statuses(clean_db) == {jobs["one"]: "active", jobs["two"]: "withdrawn"}


def test_a_withdrawn_match_is_reactivated_and_announced_as_such(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    run(clean_db, profile.id)
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == profile.id)
            .values(criteria={**profile.criteria, "work_modes": ["onsite"]}, content_hash="x")
        )
    run(clean_db, profile.id)
    notifier = RecordingNotifier()
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == profile.id)
            .values(criteria=profile.criteria, content_hash=profile.content_hash)
        )

    summary = run(clean_db, profile.id, notifier=notifier)

    assert summary == MatchSummary(evaluated=1, reactivated=1)
    [record] = notifier.records
    assert record.reactivated is True and record.profile_id == profile.id


# --- profiles that cannot be matched ----------------------------------------------------------


def test_an_inactive_profile_withdraws_everything_it_holds(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT, two=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    run(clean_db, profile.id)
    with clean_db.begin() as conn:
        conn.execute(update(Profile).where(Profile.id == profile.id).values(active=False))

    summary = run(clean_db, profile.id)

    assert summary == MatchSummary(withdrawn=2)
    assert set(statuses(clean_db).values()) == {"withdrawn"}


def test_a_missing_profile_is_skipped(clean_db: Engine) -> None:
    assert run(clean_db, 999) == MatchSummary(skipped=SKIP_MISSING)


def test_a_profile_waiting_for_its_embedding_is_skipped_and_keeps_its_matches(
    clean_db: Engine,
) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    run(clean_db, profile.id)
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == profile.id)
            .values(embedding_status=EmbeddingStatus.PENDING)
        )

    summary = run(clean_db, profile.id)

    assert summary == MatchSummary(skipped=SKIP_NOT_READY)
    assert set(statuses(clean_db).values()) == {"active"}


def test_a_never_embedded_profile_is_skipped(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY, embed=False)

    assert run(clean_db, profile.id) == MatchSummary(skipped=SKIP_NOT_READY)
    assert match_rows(clean_db) == []


def test_a_ready_profile_with_no_stored_vector_is_skipped(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)
    with clean_db.begin() as conn:
        conn.execute(delete(ProfileEmbedding).where(ProfileEmbedding.profile_id == profile.id))

    assert run(clean_db, profile.id) == MatchSummary(skipped=SKIP_NOT_READY)


def test_a_notifier_that_raises_does_not_fail_matching_a_profile(clean_db: Engine) -> None:
    indexed_jobs(clean_db, one=RECENT)
    profile = add_profile(clean_db, summary=SUMMARY)

    summary = run(clean_db, profile.id, notifier=FailingNotifier())

    assert summary.created == 1
    assert match_rows(clean_db)[0]["notified_at"] is None
