"""What the matcher reads: vectors, nearest profiles, exact cosines and views."""

import pytest
from sqlalchemy import Engine, text, update

from sanket.matching.loaders import (
    job_cosines,
    load_job_vector,
    load_job_views,
    load_profile_vector,
    load_profile_views,
    nearest_profiles,
)
from sanket.models import EmbeddingStatus, Profile
from tests.index_helpers import SPEC, set_posting_count
from tests.match_helpers import add_profile, config, index_all, seed_job

JOB_SUMMARY = "backend engineer python postgresql apis"


@pytest.fixture
def indexed_job(clean_db: Engine) -> tuple[Engine, int, list[float]]:
    job_id = seed_job(clean_db, title="Backend Engineer")
    index_all(clean_db)
    with clean_db.connect() as conn:
        vector = load_job_vector(conn, job_id, SPEC)
    assert vector is not None
    return clean_db, job_id, vector.embedding


def ids_of(found: list[tuple[int, float]]) -> list[int]:
    return [profile_id for profile_id, _ in found]


# --- vectors ----------------------------------------------------------------------------------


def test_job_vector_has_the_embedding_hash_and_is_none_for_other_specs_and_dead_jobs(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, job_id, _ = indexed_job
    other_version = SPEC.__class__(SPEC.model_name, "2", SPEC.dimensions)

    with engine.connect() as conn:
        found = load_job_vector(conn, job_id, SPEC)
        missing_version = load_job_vector(conn, job_id, other_version)
        missing_job = load_job_vector(conn, job_id + 99, SPEC)
    set_posting_count(engine, job_id, 0)
    with engine.connect() as conn:
        dead = load_job_vector(conn, job_id, SPEC)

    assert found is not None and found.entity_id == job_id and len(found.embedding) == 768
    assert found.content_hash
    assert (missing_version, missing_job, dead) == (None, None, None)


def test_profile_vector_is_none_until_the_profile_is_embedded(clean_db: Engine) -> None:
    pending = add_profile(clean_db, name="Pending", embed=False)
    ready = add_profile(clean_db, name="Ready", summary=JOB_SUMMARY)
    other_version = SPEC.__class__(SPEC.model_name, "2", SPEC.dimensions)

    with clean_db.connect() as conn:
        assert load_profile_vector(conn, pending.id, SPEC) is None
        found = load_profile_vector(conn, ready.id, SPEC)
        assert load_profile_vector(conn, ready.id, other_version) is None

    assert found is not None and found.entity_id == ready.id and len(found.embedding) == 768


# --- nearest profiles -------------------------------------------------------------------------


def test_nearest_profiles_are_ordered_by_cosine_best_first(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, _, vector = indexed_job
    far = add_profile(engine, name="Far", summary="gardening tomatoes greenhouse compost")
    near = add_profile(engine, name="Near", summary=JOB_SUMMARY)
    middle = add_profile(engine, name="Middle", summary="engineer gardening tomatoes")

    found = nearest_profiles(vector, config(), engine)

    assert ids_of(found) == [near.id, middle.id, far.id]
    cosines = [cosine for _, cosine in found]
    assert cosines == sorted(cosines, reverse=True)
    assert 0.0 < cosines[0] <= 1.0 + 1e-9


def test_nearest_profiles_only_return_active_ready_profiles(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, _, vector = indexed_job
    good = add_profile(engine, name="Good", summary=JOB_SUMMARY)
    inactive = add_profile(engine, name="Inactive", summary=JOB_SUMMARY, active=False)
    failed = add_profile(engine, name="Failed", summary=JOB_SUMMARY + " one")
    stale = add_profile(engine, name="Stale", summary=JOB_SUMMARY + " two")
    unembedded = add_profile(engine, name="Unembedded", summary=JOB_SUMMARY, embed=False)
    with engine.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == failed.id)
            .values(embedding_status=EmbeddingStatus.FAILED)
        )
        conn.execute(
            update(Profile)
            .where(Profile.id == stale.id)
            .values(embedding_status=EmbeddingStatus.PENDING)
        )

    found = nearest_profiles(vector, config(), engine)

    assert ids_of(found) == [good.id]
    assert inactive.id not in ids_of(found) and unembedded.id not in ids_of(found)


def test_nearest_profiles_only_compare_vectors_of_the_configured_model_and_version(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, _, vector = indexed_job
    current = add_profile(engine, name="Current", summary=JOB_SUMMARY)
    old = add_profile(engine, name="Old", summary=JOB_SUMMARY)
    with engine.begin() as conn:
        conn.execute(
            text("update profile_embedding set model_version = '0' where profile_id = :id"),
            {"id": old.id},
        )

    found = nearest_profiles(vector, config(), engine)

    assert ids_of(found) == [current.id]


def test_nearest_profiles_stop_at_max_profiles_per_job(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, _, vector = indexed_job
    ranked = [
        add_profile(engine, name="One", summary=JOB_SUMMARY),
        add_profile(engine, name="Two", summary="backend engineer python tomatoes gardening"),
        add_profile(engine, name="Three", summary="gardening tomatoes greenhouse compost"),
    ]

    found = nearest_profiles(vector, config(max_profiles_per_job=2), engine)

    assert ids_of(found) == [ranked[0].id, ranked[1].id]


def test_nearest_profiles_with_no_profiles_is_empty(
    indexed_job: tuple[Engine, int, list[float]],
) -> None:
    engine, _, vector = indexed_job

    assert nearest_profiles(vector, config(), engine) == []


# --- exact cosines of jobs --------------------------------------------------------------------


def test_job_cosines_are_exact_and_ignore_dead_jobs_and_other_model_versions(
    clean_db: Engine,
) -> None:
    engine = clean_db
    alive = seed_job(engine, title="Backend Engineer")
    dead = seed_job(engine, title="Backend Engineer Two")
    old = seed_job(engine, title="Backend Engineer Three")
    index_all(engine)
    set_posting_count(engine, dead, 0)
    with engine.begin() as conn:
        conn.execute(
            text("update job_embedding set model_version = '0' where job_id = :id"), {"id": old}
        )
    profile = add_profile(engine, summary=JOB_SUMMARY)
    with engine.connect() as conn:
        profile_vector = load_profile_vector(conn, profile.id, SPEC)
        job_vector = load_job_vector(conn, alive, SPEC)
    assert profile_vector is not None and job_vector is not None

    with engine.connect() as conn:
        found = job_cosines(conn, [alive, dead, old, alive + 999], profile_vector.embedding, SPEC)
        nothing = job_cosines(conn, [], profile_vector.embedding, SPEC)

    assert set(found) == {alive}
    content_hash, cosine = found[alive]
    assert content_hash == job_vector.content_hash
    expected = sum(a * b for a, b in zip(profile_vector.embedding, job_vector.embedding))
    assert cosine == pytest.approx(expected, abs=1e-6)
    assert nothing == {}


# --- views ------------------------------------------------------------------------------------


def test_load_profile_views_returns_views_and_rows(clean_db: Engine) -> None:
    profile = add_profile(
        clean_db, required_skills=["Python"], seniorities=["senior"], countries=["de"]
    )

    with clean_db.connect() as conn:
        views, rows = load_profile_views(conn, [profile.id, profile.id + 50])
        empty_views, empty_rows = load_profile_views(conn, [])

    assert set(views) == {profile.id} and set(rows) == {profile.id}
    view = views[profile.id]
    assert view.required_skills == ("Python",)
    assert view.seniorities == frozenset({"senior"}) and view.countries == frozenset({"DE"})
    assert view.owner_id == profile.owner_id and view.content_hash == profile.content_hash
    assert rows[profile.id].embedding_status == EmbeddingStatus.READY
    assert (empty_views, empty_rows) == ({}, {})


def test_a_profile_whose_stored_criteria_no_longer_validate_is_skipped_but_its_row_is_kept(
    clean_db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    good = add_profile(clean_db, name="Good")
    broken = add_profile(clean_db, name="Broken")
    with clean_db.begin() as conn:
        conn.execute(
            update(Profile)
            .where(Profile.id == broken.id)
            .values(criteria={"seniorities": ["wizard"]})
        )

    with caplog.at_level("WARNING"), clean_db.connect() as conn:
        views, rows = load_profile_views(conn, [good.id, broken.id])

    assert set(views) == {good.id}
    assert set(rows) == {good.id, broken.id}
    assert f"Profile {broken.id}" in caplog.text


def test_job_views_carry_the_extraction_and_the_given_hash(clean_db: Engine) -> None:
    job_id = seed_job(
        clean_db,
        title="Staff Engineer",
        location="Berlin, Germany",
        seniority="lead",
        work_mode="hybrid",
        employment_type="contract",
        country="SE",
        skills=["Python", "Go"],
    )

    views = load_job_views([job_id], {job_id: "the-hash"}, clean_db)

    view = views[job_id]
    assert (view.title, view.location) == ("Staff Engineer", "Berlin, Germany")
    assert (view.seniority, view.work_mode, view.employment_type) == ("lead", "hybrid", "contract")
    assert view.country == "SE" and view.skills == ("Python", "Go")
    assert view.embedding_hash == "the-hash"


def test_job_views_map_unknown_enums_to_none(clean_db: Engine) -> None:
    job_id = seed_job(
        clean_db,
        seniority="unknown",
        work_mode="unknown",
        employment_type="unknown",
        country=None,
        skills=[],
    )

    view = load_job_views([job_id], {job_id: "h"}, clean_db)[job_id]

    assert (view.seniority, view.work_mode, view.employment_type, view.country) == (
        None,
        None,
        None,
        None,
    )
    assert view.skills == ()


def test_job_views_only_cover_jobs_with_a_hash(clean_db: Engine) -> None:
    with_hash = seed_job(clean_db, title="One")
    without_hash = seed_job(clean_db, title="Two")

    views = load_job_views([with_hash, without_hash, 9999], {with_hash: "h"}, clean_db)

    assert set(views) == {with_hash}


def test_a_job_without_a_valid_extraction_has_no_enum_values_or_skills(
    clean_db: Engine,
) -> None:
    job_id = seed_job(clean_db)
    with clean_db.begin() as conn:
        conn.execute(text("update posting_extraction set data = '{\"junk\": 1}'::jsonb"))

    view = load_job_views([job_id], {job_id: "h"}, clean_db)[job_id]

    assert (view.seniority, view.work_mode, view.employment_type, view.country) == (
        None,
        None,
        None,
        None,
    )
    assert view.skills == ()
