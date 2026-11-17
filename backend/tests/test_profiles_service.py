"""The profile service against the test database: owner scoping, idempotency, queueing."""

import pytest
from sqlalchemy import Engine, select

from sanket.models import Profile, ProfileEmbedding
from sanket.profiles import service
from sanket.profiles.service import (
    ProfileInvalidError,
    ProfileLimitError,
    ProfileNameTakenError,
    ProfileNotFoundError,
)
from sanket.queue.base import EnqueueResult
from sanket.queue.memory import InMemoryTaskQueue
from sanket.queue.tasks import TASK_EMBED_PROFILE
from tests.match_helpers import OWNER, add_profile, profile_body

LIMIT = 5


def create(engine: Engine, queue: InMemoryTaskQueue | None, owner: str = OWNER, **body: object):
    return service.create_profile(
        owner, profile_body(**body), queue=queue, max_profiles=LIMIT, db_engine=engine
    )


class BrokenQueue:
    def enqueue(self, *args: object, **kwargs: object) -> EnqueueResult:
        raise ConnectionError("redis is down")


# --- create -------------------------------------------------------------------------------


def test_creating_stores_the_profile_pending_and_queues_the_embedding(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()

    saved = create(clean_db, queue, required_skills=["Python"])

    assert saved.created is True
    profile = saved.profile
    assert (profile.owner_id, profile.name, profile.active) == (OWNER, "Backend", True)
    assert profile.embedding_status == "pending"
    assert profile.criteria["required_skills"] == ["Python"]
    assert "Required skills: Python" in profile.search_text
    [task] = queue.pending(TASK_EMBED_PROFILE)
    assert task.payload == {"profile_id": profile.id, "content_hash": profile.content_hash}


def test_creating_the_same_profile_again_is_idempotent(clean_db: Engine) -> None:
    queue = InMemoryTaskQueue()
    first = create(clean_db, queue)

    second = create(clean_db, queue)

    assert second.created is False
    assert second.profile.id == first.profile.id
    assert len(service.list_for_owner(OWNER, clean_db)) == 1
    assert len(queue.pending()) == 1  # the same key, not queued twice


def test_a_retry_after_a_lost_task_queues_the_embedding_again(clean_db: Engine) -> None:
    create(clean_db, BrokenQueue())  # type: ignore[arg-type]
    queue = InMemoryTaskQueue()

    create(clean_db, queue)

    assert len(queue.pending(TASK_EMBED_PROFILE)) == 1


def test_the_same_name_with_different_content_is_a_conflict(clean_db: Engine) -> None:
    create(clean_db, None)

    with pytest.raises(ProfileNameTakenError):
        create(clean_db, None, summary="something else")


def test_two_owners_can_use_the_same_name(clean_db: Engine) -> None:
    mine = create(clean_db, None, owner="a")
    theirs = create(clean_db, None, owner="b")

    assert mine.profile.id != theirs.profile.id
    assert [p.id for p in service.list_for_owner("a", clean_db)] == [mine.profile.id]


def test_an_owner_cannot_exceed_the_profile_limit(clean_db: Engine) -> None:
    for number in range(LIMIT):
        create(clean_db, None, name=f"p{number}")

    with pytest.raises(ProfileLimitError):
        create(clean_db, None, name="one too many")
    create(clean_db, None, owner="someone else")  # the limit is per owner


def test_a_queue_failure_does_not_fail_the_save(clean_db: Engine) -> None:
    saved = create(clean_db, BrokenQueue())  # type: ignore[arg-type]

    assert saved.created is True
    assert service.get(OWNER, saved.profile.id, clean_db).embedding_status == "pending"


def test_without_a_queue_the_profile_is_saved_pending(clean_db: Engine) -> None:
    assert create(clean_db, None).profile.embedding_status == "pending"


# --- read, owner scoping ------------------------------------------------------------------


def test_another_owner_does_not_find_a_profile_by_id(clean_db: Engine) -> None:
    mine = create(clean_db, None, owner="a").profile

    with pytest.raises(ProfileNotFoundError):
        service.get("b", mine.id, clean_db)
    with pytest.raises(ProfileNotFoundError):
        service.get("a", mine.id + 1000, clean_db)
    assert service.list_for_owner("b", clean_db) == []


def test_another_owner_cannot_replace_patch_or_delete(clean_db: Engine) -> None:
    mine = create(clean_db, None, owner="a").profile

    with pytest.raises(ProfileNotFoundError):
        service.replace(
            "b", mine.id, profile_body(summary="hijack"), queue=None, db_engine=clean_db
        )
    with pytest.raises(ProfileNotFoundError):
        service.patch("b", mine.id, {"summary": "hijack"}, queue=None, db_engine=clean_db)
    with pytest.raises(ProfileNotFoundError):
        service.delete("b", mine.id, clean_db)

    assert service.get("a", mine.id, clean_db).criteria["summary"] == mine.criteria["summary"]


# --- replace and patch --------------------------------------------------------------------


def test_replacing_with_new_content_resets_the_status_and_queues_a_new_embedding(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db)
    assert profile.embedding_status == "ready"
    queue = InMemoryTaskQueue()

    updated = service.replace(
        OWNER,
        profile.id,
        profile_body(summary="data engineering", required_skills=["Spark"]),
        queue=queue,
        db_engine=clean_db,
    )

    assert updated.embedding_status == "pending"
    assert updated.content_hash != profile.content_hash
    assert updated.updated_at >= profile.updated_at
    [task] = queue.pending()
    assert task.payload["content_hash"] == updated.content_hash


def test_replacing_with_identical_content_changes_and_queues_nothing(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    queue = InMemoryTaskQueue()

    same = service.replace(OWNER, profile.id, profile_body(), queue=queue, db_engine=clean_db)

    assert same == profile
    assert queue.pending() == []


def test_renaming_alone_keeps_the_embedding_and_queues_nothing(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    queue = InMemoryTaskQueue()

    renamed = service.replace(
        OWNER, profile.id, profile_body(name="New name"), queue=queue, db_engine=clean_db
    )

    assert renamed.name == "New name"
    assert renamed.embedding_status == "ready"
    assert queue.pending() == []


def test_replacing_into_a_name_already_used_is_a_conflict(clean_db: Engine) -> None:
    add_profile(clean_db, name="taken")
    other = add_profile(clean_db, name="other")

    with pytest.raises(ProfileNameTakenError):
        service.replace(OWNER, other.id, profile_body(name="taken"), queue=None, db_engine=clean_db)

    assert service.get(OWNER, other.id, clean_db).name == "other"


def test_switching_a_profile_off_changes_the_hash_and_queues_a_rematch_path(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db)
    queue = InMemoryTaskQueue()

    updated = service.patch(OWNER, profile.id, {"active": False}, queue=queue, db_engine=clean_db)

    assert updated.active is False
    assert updated.content_hash != profile.content_hash
    assert len(queue.pending(TASK_EMBED_PROFILE)) == 1


def test_a_patch_changes_only_the_given_fields(clean_db: Engine) -> None:
    profile = add_profile(clean_db, required_skills=["Python"], countries=["DE"])

    updated = service.patch(
        OWNER, profile.id, {"countries": ["SE"], "name": "Renamed"}, queue=None, db_engine=clean_db
    )

    assert updated.name == "Renamed"
    assert updated.criteria["countries"] == ["SE"]
    assert updated.criteria["required_skills"] == ["Python"]
    assert updated.criteria["summary"] == profile.criteria["summary"]


def test_a_patch_that_makes_the_profile_invalid_is_refused_and_changes_nothing(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db)

    with pytest.raises(ProfileInvalidError) as caught:
        service.patch(OWNER, profile.id, {"countries": ["ZZ"]}, queue=None, db_engine=clean_db)

    assert caught.value.errors[0]["loc"] == ("countries",)
    assert service.get(OWNER, profile.id, clean_db) == profile


def test_a_patch_with_an_unknown_field_is_refused(clean_db: Engine) -> None:
    profile = add_profile(clean_db)

    with pytest.raises(ProfileInvalidError):
        service.patch(OWNER, profile.id, {"nope": 1}, queue=None, db_engine=clean_db)


# --- delete -------------------------------------------------------------------------------


def test_deleting_removes_the_profile_its_embedding_and_frees_the_name(clean_db: Engine) -> None:
    profile = add_profile(clean_db)

    service.delete(OWNER, profile.id, clean_db)

    with clean_db.connect() as conn:
        assert conn.execute(select(Profile.id)).all() == []
        assert conn.execute(select(ProfileEmbedding.id)).all() == []
    with pytest.raises(ProfileNotFoundError):
        service.delete(OWNER, profile.id, clean_db)
    assert create(clean_db, None).created is True
