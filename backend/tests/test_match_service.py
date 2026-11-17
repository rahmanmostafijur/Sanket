"""The job side of matching, end to end against the database with fake embeddings."""

import logging
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.exc import OperationalError

from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.matching import service
from sanket.matching.notify import MatchRecord
from sanket.matching.service import (
    SKIP_NO_EMBEDDING,
    MatchSummary,
    match_job,
    withdraw_job,
)
from sanket.models import EmbeddingStatus, JobEmbedding, JobMatch, Profile
from sanket.profiles.embedding import embed_profile
from sanket.profiles.service import replace
from tests.index_helpers import SPEC, set_posting_count
from tests.match_helpers import (
    OWNER,
    FailingNotifier,
    RecordingNotifier,
    add_profile,
    change_extraction,
    config,
    index_all,
    match_rows,
    profile_body,
    seed_job,
)

# The fake embedding is a bag of hashed words, so cosines are small. These settings let every
# job that passes the filters through, so each test controls the outcome with the filters.
LENIENT = config(min_cosine=-1.0, min_score=0.0)
SUMMARY = "backend engineer python postgresql apis"


def job_with_profile(engine: Engine, **profile: Any) -> tuple[int, int]:
    """An indexed remote job and a ready profile that accepts it."""
    job_id = seed_job(engine, title="Backend Engineer", work_mode="remote")
    index_all(engine)
    profile.setdefault("summary", SUMMARY)
    return job_id, add_profile(engine, **profile).id


def statuses(engine: Engine) -> dict[int, str]:
    return {row["profile_id"]: row["status"] for row in match_rows(engine)}


# --- a new match -----------------------------------------------------------------------------


def test_a_new_match_is_created_and_announced_once(clean_db: Engine) -> None:
    job_id, profile_id = job_with_profile(clean_db)
    notifier = RecordingNotifier()

    summary = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1, created=1)
    [row] = match_rows(clean_db)
    assert (row["profile_id"], row["job_id"], row["status"]) == (profile_id, job_id, "active")
    assert row["notified_at"] is not None
    [record] = notifier.records
    assert record == MatchRecord(
        match_id=row["id"],
        profile_id=profile_id,
        owner_id=OWNER,
        job_id=job_id,
        score=row["score"],
        components=row["components"],
        reactivated=False,
    )
    assert record.components["filters"]["work_mode"] == "na"


def test_matching_with_the_default_notifier_stores_the_match(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)

    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary.created == 1 and len(match_rows(clean_db)) == 1


def test_a_job_with_no_profiles_evaluates_nothing(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)

    assert match_job(job_id, LENIENT, db_engine=clean_db) == MatchSummary()


def test_the_default_thresholds_keep_an_unrelated_profile_out(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db, summary="gardening tomatoes greenhouse compost")

    summary = match_job(job_id, config(), db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1)
    assert match_rows(clean_db) == []


# --- running it again -------------------------------------------------------------------------


def test_running_again_is_a_no_op(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)
    notifier = RecordingNotifier()
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)
    before = match_rows(clean_db)

    summary = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1)
    assert match_rows(clean_db) == before
    assert len(notifier.records) == 1


def test_a_changed_extraction_updates_the_match_in_place_without_a_new_notification(
    clean_db: Engine,
) -> None:
    job_id, _ = job_with_profile(clean_db, preferred_skills=["Python", "Go"])
    notifier = RecordingNotifier()
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)
    [before] = match_rows(clean_db)

    change_extraction(clean_db, job_id, skills=["Python", "Go"])
    summary = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    [after] = match_rows(clean_db)
    assert summary == MatchSummary(evaluated=1, updated=1)
    assert after["id"] == before["id"] and after["score"] > before["score"]
    assert after["components"]["skills"]["preferred_hits"] == ["Python", "Go"]
    assert after["updated_at"] > before["updated_at"]
    assert after["notified_at"] == before["notified_at"]
    assert len(notifier.records) == 1


def test_a_changed_profile_updates_the_match_in_place(clean_db: Engine) -> None:
    job_id, profile_id = job_with_profile(clean_db)
    match_job(job_id, LENIENT, db_engine=clean_db)
    [before] = match_rows(clean_db)

    body = profile_body(summary=SUMMARY, preferred_skills=["Python"])
    replace(OWNER, profile_id, body, queue=None, db_engine=clean_db)
    embed_profile(profile_id, FakeEmbeddingClient(), SPEC, db_engine=clean_db)
    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    [after] = match_rows(clean_db)
    assert summary == MatchSummary(evaluated=1, updated=1)
    assert after["id"] == before["id"]
    assert after["profile_hash"] != before["profile_hash"]


# --- filters and withdrawing ------------------------------------------------------------------


def test_a_filter_that_now_fails_withdraws_the_match_and_a_later_pass_reactivates_it(
    clean_db: Engine,
) -> None:
    job_id, profile_id = job_with_profile(clean_db, work_modes=["remote"])
    notifier = RecordingNotifier()
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)
    [first] = match_rows(clean_db)

    change_extraction(clean_db, job_id, work_mode="onsite")
    withdrawn = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert withdrawn == MatchSummary(evaluated=1, withdrawn=1)
    [row] = match_rows(clean_db)
    assert row["status"] == "withdrawn" and row["id"] == first["id"]
    assert row["components"]["filters"]["work_mode"] == "fail"
    assert len(notifier.records) == 1

    change_extraction(clean_db, job_id, work_mode="remote")
    back = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert back == MatchSummary(evaluated=1, reactivated=1)
    [again] = match_rows(clean_db)
    assert (again["id"], again["status"]) == (first["id"], "active")
    assert [r.reactivated for r in notifier.records] == [False, True]
    assert notifier.records[1].match_id == first["id"]
    assert again["notified_at"] is not None
    assert profile_id == again["profile_id"]


def test_a_dead_job_withdraws_all_its_matches(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)
    add_profile(clean_db, name="Second", summary=SUMMARY)
    match_job(job_id, LENIENT, db_engine=clean_db)
    assert list(statuses(clean_db).values()) == ["active", "active"]

    set_posting_count(clean_db, job_id, 0)
    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary == MatchSummary(withdrawn=2, skipped=SKIP_NO_EMBEDDING)
    assert set(statuses(clean_db).values()) == {"withdrawn"}


def test_a_job_with_no_embedding_withdraws_all_its_matches(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)
    match_job(job_id, LENIENT, db_engine=clean_db)

    with clean_db.begin() as conn:
        conn.execute(delete(JobEmbedding).where(JobEmbedding.job_id == job_id))
    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary.withdrawn == 1 and summary.skipped == SKIP_NO_EMBEDDING
    assert set(statuses(clean_db).values()) == {"withdrawn"}


def test_withdraw_job_withdraws_without_looking_at_embeddings(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)
    match_job(job_id, LENIENT, db_engine=clean_db)

    summary = withdraw_job(job_id, clean_db)
    again = withdraw_job(job_id, clean_db)

    assert summary == MatchSummary(withdrawn=1, skipped=SKIP_NO_EMBEDDING)
    assert again.withdrawn == 0
    assert set(statuses(clean_db).values()) == {"withdrawn"}


def test_an_unknown_job_is_treated_as_having_no_embedding(clean_db: Engine) -> None:
    summary = match_job(4242, LENIENT, db_engine=clean_db)

    assert summary == MatchSummary(skipped=SKIP_NO_EMBEDDING)


# --- profiles that are no longer among the candidates ----------------------------------------


def two_profiles_matched(engine: Engine) -> tuple[int, int, int]:
    """A job matched by a near and a far profile: (job id, near id, far id)."""
    job_id = seed_job(engine, title="Backend Engineer")
    index_all(engine)
    near = add_profile(engine, name="Near", summary=SUMMARY).id
    far = add_profile(engine, name="Far", summary="engineer gardening tomatoes").id
    assert match_job(job_id, LENIENT, db_engine=engine).created == 2
    return job_id, near, far


def test_a_ready_profile_outranked_by_the_candidate_limit_is_withdrawn(
    clean_db: Engine,
) -> None:
    job_id, near, far = two_profiles_matched(clean_db)

    summary = match_job(job_id, config(max_profiles_per_job=1, **_lenient()), db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1, withdrawn=1)
    assert statuses(clean_db) == {near: "active", far: "withdrawn"}


def test_an_inactive_profile_that_was_matched_is_withdrawn(clean_db: Engine) -> None:
    job_id, near, far = two_profiles_matched(clean_db)
    with clean_db.begin() as conn:
        conn.execute(update(Profile).where(Profile.id == far).values(active=False))

    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1, withdrawn=1)
    assert statuses(clean_db) == {near: "active", far: "withdrawn"}


def test_a_profile_waiting_for_its_embedding_keeps_its_matches(clean_db: Engine) -> None:
    job_id, near, far = two_profiles_matched(clean_db)
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == far)
            .values(embedding_status=EmbeddingStatus.PENDING)
        )

    summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1)
    assert statuses(clean_db) == {near: "active", far: "active"}


def test_a_profile_whose_criteria_no_longer_validate_is_skipped_and_keeps_its_match(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    job_id, near, far = two_profiles_matched(clean_db)
    with clean_db.begin() as conn:
        conn.execute(update(Profile).where(Profile.id == far).values(criteria={"x": 1}))

    with caplog.at_level(logging.WARNING):
        summary = match_job(job_id, LENIENT, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1)
    assert statuses(clean_db) == {near: "active", far: "active"}
    assert f"Profile {far}" in caplog.text


def _lenient() -> dict[str, float]:
    return {"min_cosine": -1.0, "min_score": 0.0}


# --- the notifier -----------------------------------------------------------------------------


class ReadingNotifier(RecordingNotifier):
    """Reads the match from the database, as a subscriber that publishes it would."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self.seen: list[Any] = []

    def notify(self, match: MatchRecord) -> None:
        super().notify(match)
        with self.engine.connect() as conn:
            self.seen.append(
                conn.execute(select(JobMatch).where(JobMatch.id == match.match_id)).one_or_none()
            )


def test_the_notifier_runs_after_the_commit_and_finds_the_row(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db)
    notifier = ReadingNotifier(clean_db)

    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    [seen] = notifier.seen
    assert seen is not None and seen.status == "active"
    # Not marked yet while the hook runs: that is recorded once the hook has returned.
    assert seen.notified_at is None
    assert match_rows(clean_db)[0]["notified_at"] is not None


def test_a_notifier_that_raises_is_logged_and_the_match_stays_unnotified(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    job_id, _ = job_with_profile(clean_db)
    notifier = FailingNotifier()

    with caplog.at_level(logging.ERROR):
        summary = match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert summary == MatchSummary(evaluated=1, created=1)
    [row] = match_rows(clean_db)
    assert row["status"] == "active" and row["notified_at"] is None
    assert "Notifying match" in caplog.text and "pub/sub is down" in caplog.text

    retry = RecordingNotifier()
    assert match_job(job_id, LENIENT, notifier=retry, db_engine=clean_db).created == 0
    assert retry.records == []  # the stored match is not new; notified_at is the marker


class FlakyNotifier(RecordingNotifier):
    def __init__(self, fail_for: set[int]) -> None:
        super().__init__()
        self.fail_for = fail_for

    def notify(self, match: MatchRecord) -> None:
        if match.profile_id in self.fail_for:
            raise ConnectionError("down")
        super().notify(match)


def test_notified_at_is_set_only_for_the_matches_that_were_delivered(clean_db: Engine) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)
    first = add_profile(clean_db, name="First", summary=SUMMARY).id
    second = add_profile(clean_db, name="Second", summary=SUMMARY).id

    summary = match_job(job_id, LENIENT, notifier=FlakyNotifier({first}), db_engine=clean_db)

    assert summary.created == 2
    stamps = {row["profile_id"]: row["notified_at"] for row in match_rows(clean_db)}
    assert stamps[first] is None and stamps[second] is not None


def test_a_failure_to_record_the_notifications_is_logged_not_raised(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    job_id, _ = job_with_profile(clean_db)

    def broken(conn: Any, ids: Any) -> None:
        raise OperationalError("update", {}, ConnectionError("gone"))

    monkeypatch.setattr(service, "mark_notified", broken)
    with caplog.at_level(logging.ERROR):
        summary = match_job(job_id, LENIENT, notifier=RecordingNotifier(), db_engine=clean_db)

    assert summary.created == 1
    assert match_rows(clean_db)[0]["notified_at"] is None
    assert "Recording 1 notifications failed" in caplog.text


def test_only_new_matches_are_announced_not_updates_or_withdrawals(clean_db: Engine) -> None:
    job_id, _ = job_with_profile(clean_db, preferred_skills=["Python", "Go"], work_modes=["remote"])
    notifier = RecordingNotifier()
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    change_extraction(clean_db, job_id, skills=["Python", "Go"])
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)
    change_extraction(clean_db, job_id, work_mode="onsite")
    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert len(notifier.records) == 1


def test_two_job_matches_get_consecutive_ids_and_the_owner_of_each_profile(
    clean_db: Engine,
) -> None:
    job_id = seed_job(clean_db)
    index_all(clean_db)
    add_profile(clean_db, name="Mine", summary=SUMMARY, owner_id="owner-a")
    add_profile(clean_db, name="Theirs", summary=SUMMARY, owner_id="owner-b")
    notifier = RecordingNotifier()

    match_job(job_id, LENIENT, notifier=notifier, db_engine=clean_db)

    assert sorted(r.owner_id for r in notifier.records) == ["owner-a", "owner-b"]
    ids = sorted(r.match_id for r in notifier.records)
    assert ids[1] == ids[0] + 1
