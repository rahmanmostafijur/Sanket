"""Idempotent persistence of matches: the decision table and the writes against the database."""

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine

from sanket.matching.persist import (
    Evaluation,
    StoredMatch,
    WriteKind,
    WritePlan,
    apply_plans,
    load_stored_for_job,
    load_stored_for_profile,
    mark_notified,
    plan_write,
    withdraw_job_matches,
    withdraw_matches,
    withdraw_profile_matches,
)
from sanket.matching.score import SCORER_VERSION
from sanket.matching.types import MatchScore
from sanket.models import JobMatch, MatchStatus
from tests.match_helpers import add_profile, match_rows, seed_job

COMPONENTS: dict[str, Any] = {"cosine": {"value": 0.8}, "filters": {"country": "pass"}}


def evaluation(
    *,
    is_match: bool = True,
    score: float = 0.7,
    components: dict[str, Any] | None = None,
    job_hash: str = "jh",
    profile_hash: str = "ph",
    profile_id: int = 1,
    job_id: int = 1,
) -> Evaluation:
    result = MatchScore(
        score=score,
        components=COMPONENTS if components is None else components,
        passed_filters=is_match,
        is_match=is_match,
    )
    return Evaluation(profile_id, job_id, result, job_hash, profile_hash)


def stored(
    *,
    status: str = MatchStatus.ACTIVE,
    score: float = 0.7,
    components: dict[str, Any] | None = None,
    scorer_version: int = SCORER_VERSION,
    job_hash: str = "jh",
    profile_hash: str = "ph",
    notified_at: datetime | None = None,
) -> StoredMatch:
    return StoredMatch(
        id=10,
        profile_id=1,
        job_id=1,
        score=score,
        components=COMPONENTS if components is None else components,
        scorer_version=scorer_version,
        status=status,
        job_embedding_hash=job_hash,
        profile_hash=profile_hash,
        notified_at=notified_at,
    )


NOTIFIED = datetime(2026, 11, 1, tzinfo=UTC)

# --- the decision table, every row -----------------------------------------------------------


def test_nothing_stored_and_a_match_inserts_an_active_row_to_announce() -> None:
    plan = plan_write(None, evaluation())

    assert plan is not None
    assert (plan.kind, plan.status, plan.notified_at) == (WriteKind.INSERT, "active", None)
    assert plan.is_new is True
    assert plan.touches_updated_at is True


def test_nothing_stored_and_not_a_match_writes_nothing() -> None:
    assert plan_write(None, evaluation(is_match=False)) is None


def test_active_and_unchanged_writes_nothing() -> None:
    assert plan_write(stored(notified_at=NOTIFIED), evaluation()) is None


def test_active_and_a_new_score_updates_in_place_keeping_notified_at() -> None:
    plan = plan_write(stored(notified_at=NOTIFIED), evaluation(score=0.9))

    assert plan is not None
    assert (plan.kind, plan.status, plan.notified_at) == (WriteKind.UPDATE, "active", NOTIFIED)
    assert plan.is_new is False
    assert plan.touches_updated_at is True


def test_active_and_other_components_updates_in_place() -> None:
    plan = plan_write(stored(), evaluation(components={"cosine": {"value": 0.81}}))

    assert plan is not None and plan.kind is WriteKind.UPDATE


def test_active_and_another_scorer_version_updates_in_place() -> None:
    plan = plan_write(stored(scorer_version=SCORER_VERSION + 1), evaluation())

    assert plan is not None and plan.kind is WriteKind.UPDATE


def test_active_with_only_other_hashes_updates_just_the_hashes() -> None:
    for changed in ({"job_hash": "jh2"}, {"profile_hash": "ph2"}):
        plan = plan_write(stored(notified_at=NOTIFIED), evaluation(**changed))

        assert plan is not None
        assert plan.kind is WriteKind.HASHES
        assert plan.touches_updated_at is False
        assert plan.is_new is False
        assert plan.notified_at == NOTIFIED


def test_active_and_no_longer_a_match_withdraws_with_the_new_score() -> None:
    plan = plan_write(stored(notified_at=NOTIFIED), evaluation(is_match=False, score=0.2))

    assert plan is not None
    assert (plan.kind, plan.status, plan.notified_at) == (
        WriteKind.WITHDRAW,
        "withdrawn",
        NOTIFIED,
    )
    assert plan.evaluation.score.score == 0.2
    assert plan.is_new is False


def test_withdrawn_and_a_match_again_reactivates_and_resets_notified_at() -> None:
    plan = plan_write(stored(status="withdrawn", notified_at=NOTIFIED), evaluation())

    assert plan is not None
    assert (plan.kind, plan.status, plan.notified_at) == (WriteKind.REACTIVATE, "active", None)
    assert plan.is_new is True


def test_withdrawn_and_still_not_a_match_writes_nothing() -> None:
    assert plan_write(stored(status="withdrawn"), evaluation(is_match=False)) is None


# --- the writes -------------------------------------------------------------------------------


@pytest.fixture
def pair(clean_db: Engine) -> tuple[Engine, int, int]:
    """The engine, a job id and a profile id to hang matches on."""
    return clean_db, seed_job(clean_db), add_profile(clean_db, embed=False).id


def write(engine: Engine, plans: list[WritePlan]) -> dict[tuple[int, int], int]:
    with engine.begin() as conn:
        return apply_plans(conn, plans)


def plan_for(engine: Engine, ev: Evaluation) -> WritePlan | None:
    """Plan against what is stored now, the way the service does."""
    with engine.begin() as conn:
        current = load_stored_for_job(conn, ev.job_id, [ev.profile_id])
    return plan_write(current.get((ev.profile_id, ev.job_id)), ev)


def insert_match(engine: Engine, job_id: int, profile_id: int, **overrides: Any) -> int:
    ev = evaluation(job_id=job_id, profile_id=profile_id, **overrides)
    plan = plan_for(engine, ev)
    assert plan is not None
    return write(engine, [plan])[(profile_id, job_id)]


def test_a_new_match_is_inserted_active_and_not_yet_notified(
    pair: tuple[Engine, int, int],
) -> None:
    engine, job_id, profile_id = pair

    match_id = insert_match(engine, job_id, profile_id)

    [row] = match_rows(engine)
    assert row["id"] == match_id
    assert (row["status"], row["notified_at"], row["scorer_version"]) == (
        "active",
        None,
        SCORER_VERSION,
    )
    assert (row["score"], row["components"]) == (0.7, COMPONENTS)
    assert (row["job_embedding_hash"], row["profile_hash"]) == ("jh", "ph")


def test_a_second_identical_run_changes_nothing(pair: tuple[Engine, int, int]) -> None:
    engine, job_id, profile_id = pair
    first_id = insert_match(engine, job_id, profile_id)
    before = match_rows(engine)

    again = plan_for(engine, evaluation(job_id=job_id, profile_id=profile_id))
    ids = write(engine, [] if again is None else [again])

    assert again is None and ids == {}
    assert match_rows(engine) == before
    # No sequence value was used by the second run: the next match gets the next id.
    other_profile = add_profile(engine, name="Other", embed=False).id
    assert insert_match(engine, job_id, other_profile) == first_id + 1


def test_a_changed_score_updates_the_same_row_and_moves_updated_at(
    pair: tuple[Engine, int, int],
) -> None:
    engine, job_id, profile_id = pair
    first_id = insert_match(engine, job_id, profile_id)
    before = match_rows(engine)[0]

    ev = evaluation(job_id=job_id, profile_id=profile_id, score=0.9)
    plan = plan_for(engine, ev)
    assert plan is not None
    ids = write(engine, [plan])

    [row] = match_rows(engine)
    assert ids == {(profile_id, job_id): first_id}
    assert row["id"] == first_id and row["score"] == 0.9
    assert row["updated_at"] > before["updated_at"]
    assert row["created_at"] == before["created_at"]


def test_a_hashes_only_update_leaves_updated_at_alone(pair: tuple[Engine, int, int]) -> None:
    engine, job_id, profile_id = pair
    insert_match(engine, job_id, profile_id)
    before = match_rows(engine)[0]

    plan = plan_for(engine, evaluation(job_id=job_id, profile_id=profile_id, job_hash="jh2"))
    assert plan is not None and plan.kind is WriteKind.HASHES
    write(engine, [plan])

    [row] = match_rows(engine)
    assert row["job_embedding_hash"] == "jh2"
    assert row["updated_at"] == before["updated_at"]
    assert (row["score"], row["status"]) == (before["score"], "active")


def test_withdrawing_stores_the_new_score_and_keeps_the_row_and_its_id(
    pair: tuple[Engine, int, int],
) -> None:
    engine, job_id, profile_id = pair
    match_id = insert_match(engine, job_id, profile_id)
    with engine.begin() as conn:
        mark_notified(conn, [match_id])

    plan = plan_for(
        engine, evaluation(job_id=job_id, profile_id=profile_id, is_match=False, score=0.1)
    )
    assert plan is not None
    write(engine, [plan])

    [row] = match_rows(engine)
    assert (row["id"], row["status"], row["score"]) == (match_id, "withdrawn", 0.1)
    assert row["notified_at"] is not None


def test_reactivating_resets_notified_at_and_keeps_the_id(pair: tuple[Engine, int, int]) -> None:
    engine, job_id, profile_id = pair
    match_id = insert_match(engine, job_id, profile_id)
    with engine.begin() as conn:
        mark_notified(conn, [match_id])
        withdraw_matches(conn, [match_id])

    plan = plan_for(engine, evaluation(job_id=job_id, profile_id=profile_id))
    assert plan is not None and plan.kind is WriteKind.REACTIVATE
    write(engine, [plan])

    [row] = match_rows(engine)
    assert (row["id"], row["status"], row["notified_at"]) == (match_id, "active", None)


def test_a_batch_of_mixed_plans_writes_each_kind(clean_db: Engine) -> None:
    engine = clean_db
    job_id = seed_job(engine)
    profiles = [add_profile(engine, name=f"P{n}", embed=False).id for n in range(3)]
    insert_match(engine, job_id, profiles[1])
    insert_match(engine, job_id, profiles[2])

    evaluations = [
        evaluation(job_id=job_id, profile_id=profiles[0]),
        evaluation(job_id=job_id, profile_id=profiles[1], score=0.95),
        evaluation(job_id=job_id, profile_id=profiles[2], job_hash="jh2"),
    ]
    with engine.begin() as conn:
        current = load_stored_for_job(conn, job_id, profiles)
        plans = [plan_write(current.get((e.profile_id, e.job_id)), e) for e in evaluations]
    assert [p.kind for p in plans if p] == [WriteKind.INSERT, WriteKind.UPDATE, WriteKind.HASHES]
    ids = write(engine, [p for p in plans if p])

    assert set(ids) == {(p, job_id) for p in profiles}
    by_profile = {row["profile_id"]: row for row in match_rows(engine)}
    assert by_profile[profiles[1]]["score"] == 0.95
    assert by_profile[profiles[2]]["job_embedding_hash"] == "jh2"


# --- loading under lock ------------------------------------------------------------------------


def test_load_for_a_job_returns_the_asked_profiles_and_all_active_matches(
    clean_db: Engine,
) -> None:
    engine = clean_db
    job_id = seed_job(engine)
    p1, p2, p3 = (add_profile(engine, name=f"P{n}", embed=False).id for n in range(3))
    for profile_id in (p1, p2, p3):
        insert_match(engine, job_id, profile_id)
    with engine.begin() as conn:
        withdraw_profile_matches(conn, p2)
        withdraw_profile_matches(conn, p3)

    with engine.begin() as conn:
        asked = load_stored_for_job(conn, job_id, [p2])

    # p2 was asked for (withdrawn but included), p1 is active (included), p3 is neither.
    assert set(asked) == {(p1, job_id), (p2, job_id)}


def test_load_for_a_profile_returns_the_asked_jobs_and_all_active_matches(
    clean_db: Engine,
) -> None:
    engine = clean_db
    profile_id = add_profile(engine, embed=False).id
    j1, j2, j3 = (seed_job(engine, title=f"Job {n}") for n in range(3))
    for job_id in (j1, j2, j3):
        insert_match(engine, job_id, profile_id)
    with engine.begin() as conn:
        withdraw_job_matches(conn, [j2, j3])

    with engine.begin() as conn:
        asked = load_stored_for_profile(conn, profile_id, [j3])

    assert set(asked) == {(profile_id, j1), (profile_id, j3)}


# --- two workers at once ------------------------------------------------------------------------


class _Race:
    """Two workers that both read the same job's matches before either writes."""

    def __init__(self, engine: Engine, job_id: int, profile_id: int) -> None:
        self.engine = engine
        self.job_id = job_id
        self.profile_id = profile_id
        self.first_has_read = threading.Event()
        self.second_has_read = threading.Event()
        self.new_for: list[str] = []
        self.errors: list[BaseException] = []

    def _worker(self, name: str, mine: threading.Event, other: threading.Event) -> None:
        try:
            ev = evaluation(job_id=self.job_id, profile_id=self.profile_id)
            with self.engine.begin() as conn:
                current = load_stored_for_job(conn, self.job_id, [self.profile_id])
                plan = plan_write(current.get((self.profile_id, self.job_id)), ev)
                mine.set()
                # Without a lock on the rows both would be here at once; with one the second
                # worker is still waiting inside the read above, so give up waiting.
                other.wait(timeout=0.7)
                if plan is not None:
                    written = apply_plans(conn, [plan])
                    if plan.is_new and (self.profile_id, self.job_id) in written:
                        self.new_for.append(name)
        except BaseException as error:
            self.errors.append(error)
            raise

    def run(self) -> None:
        first = threading.Thread(
            target=self._worker, args=("a", self.first_has_read, self.second_has_read)
        )
        second = threading.Thread(
            target=self._worker, args=("b", self.second_has_read, self.first_has_read)
        )
        first.start()
        assert self.first_has_read.wait(timeout=10)
        second.start()
        first.join(timeout=30)
        second.join(timeout=30)
        assert not first.is_alive() and not second.is_alive()
        assert self.errors == []


def test_two_workers_do_not_both_reactivate_a_withdrawn_match(
    pair: tuple[Engine, int, int],
) -> None:
    engine, job_id, profile_id = pair
    match_id = insert_match(engine, job_id, profile_id)
    with engine.begin() as conn:
        withdraw_matches(conn, [match_id])

    race = _Race(engine, job_id, profile_id)
    race.run()

    assert len(race.new_for) == 1
    [row] = match_rows(engine)
    assert (row["id"], row["status"]) == (match_id, "active")


def test_two_workers_do_not_both_insert_the_same_new_match(pair: tuple[Engine, int, int]) -> None:
    engine, job_id, profile_id = pair

    race = _Race(engine, job_id, profile_id)
    race.run()

    assert len(race.new_for) == 1
    assert len(match_rows(engine)) == 1


# --- withdraw helpers and mark_notified --------------------------------------------------------


def test_withdraw_matches_only_touches_active_rows_and_counts_them(clean_db: Engine) -> None:
    engine = clean_db
    job_id = seed_job(engine)
    p1, p2 = (add_profile(engine, name=f"P{n}", embed=False).id for n in range(2))
    m1 = insert_match(engine, job_id, p1)
    m2 = insert_match(engine, job_id, p2)
    with engine.begin() as conn:
        assert withdraw_matches(conn, [m1]) == 1
    withdrawn_at = {row["id"]: row["updated_at"] for row in match_rows(engine)}

    with engine.begin() as conn:
        assert withdraw_matches(conn, [m1, m2]) == 1  # m1 is already withdrawn
        assert withdraw_matches(conn, []) == 0

    rows = {row["id"]: row for row in match_rows(engine)}
    assert [rows[m1]["status"], rows[m2]["status"]] == ["withdrawn", "withdrawn"]
    assert rows[m1]["updated_at"] == withdrawn_at[m1]


def test_withdraw_job_matches_withdraws_every_active_match_of_those_jobs(
    clean_db: Engine,
) -> None:
    engine = clean_db
    profile_id = add_profile(engine, embed=False).id
    j1, j2, j3 = (seed_job(engine, title=f"Job {n}") for n in range(3))
    for job_id in (j1, j2, j3):
        insert_match(engine, job_id, profile_id)

    with engine.begin() as conn:
        assert withdraw_job_matches(conn, [j1, j2]) == 2
        assert withdraw_job_matches(conn, [j1, j2]) == 0
        assert withdraw_job_matches(conn, []) == 0

    statuses = {row["job_id"]: row["status"] for row in match_rows(engine)}
    assert statuses == {j1: "withdrawn", j2: "withdrawn", j3: "active"}


def test_withdraw_profile_matches_withdraws_only_that_profiles_active_matches(
    clean_db: Engine,
) -> None:
    engine = clean_db
    job_id = seed_job(engine)
    p1, p2 = (add_profile(engine, name=f"P{n}", embed=False).id for n in range(2))
    for profile_id in (p1, p2):
        insert_match(engine, job_id, profile_id)

    with engine.begin() as conn:
        assert withdraw_profile_matches(conn, p1) == 1
        assert withdraw_profile_matches(conn, p1) == 0

    statuses = {row["profile_id"]: row["status"] for row in match_rows(engine)}
    assert statuses == {p1: "withdrawn", p2: "active"}


def test_mark_notified_fills_only_null_timestamps(clean_db: Engine) -> None:
    engine = clean_db
    job_id = seed_job(engine)
    p1, p2 = (add_profile(engine, name=f"P{n}", embed=False).id for n in range(2))
    m1 = insert_match(engine, job_id, p1)
    m2 = insert_match(engine, job_id, p2)
    long_ago = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            JobMatch.__table__.update().where(JobMatch.id == m1).values(notified_at=long_ago)
        )

    with engine.begin() as conn:
        mark_notified(conn, [m1, m2])
        mark_notified(conn, [])

    rows = {row["id"]: row for row in match_rows(engine)}
    assert rows[m1]["notified_at"] == long_ago
    assert rows[m2]["notified_at"] is not None and rows[m2]["notified_at"] > long_ago


def test_mark_notified_does_not_touch_updated_at(pair: tuple[Engine, int, int]) -> None:
    engine, job_id, profile_id = pair
    match_id = insert_match(engine, job_id, profile_id)
    before = match_rows(engine)[0]["updated_at"]

    with engine.begin() as conn:
        mark_notified(conn, [match_id])

    assert match_rows(engine)[0]["updated_at"] == before
