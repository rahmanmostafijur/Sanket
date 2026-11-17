"""Reading matches by id and the latest match id (what the live feed builds on)."""

from sqlalchemy import Engine, update

from sanket.matching.matches import get_active_matches, latest_match_id
from sanket.models import JobMatch
from tests.test_profile_schema import add_match, add_profile, new_job


def match_for(engine: Engine, profile_id: int) -> int:
    return add_match(engine, profile_id, new_job(engine))


def test_the_latest_id_is_zero_for_a_profile_without_matches(clean_db: Engine) -> None:
    assert latest_match_id(add_profile(clean_db), clean_db) == 0


def test_the_latest_id_is_the_highest_of_that_profile_withdrawn_included(clean_db: Engine) -> None:
    profile = add_profile(clean_db, name="a")
    other = add_profile(clean_db, name="b")
    first, second = match_for(clean_db, profile), match_for(clean_db, profile)
    match_for(clean_db, other)
    with clean_db.begin() as conn:
        conn.execute(update(JobMatch).where(JobMatch.id == second).values(status="withdrawn"))

    assert latest_match_id(profile, clean_db) == second > first


def test_active_matches_by_id_are_ascending_and_skip_foreign_and_withdrawn_ones(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, name="a")
    other = add_profile(clean_db, name="b")
    ids = [match_for(clean_db, profile) for _ in range(3)]
    foreign = match_for(clean_db, other)
    with clean_db.begin() as conn:
        conn.execute(update(JobMatch).where(JobMatch.id == ids[0]).values(status="withdrawn"))

    items = get_active_matches(profile, [ids[2], foreign, ids[1], ids[0], 9999], clean_db)

    assert [item.id for item in items] == [ids[1], ids[2]]
    assert all(item.status == "active" for item in items)


def test_no_ids_read_nothing(clean_db: Engine) -> None:
    assert get_active_matches(1, [], clean_db) == []
