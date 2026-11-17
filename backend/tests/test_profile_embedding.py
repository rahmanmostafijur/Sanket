"""Embedding profiles: the hash gate, status transitions, outages and races."""

from dataclasses import replace

import pytest
from sqlalchemy import Engine, select

from sanket.embeddings.client import EmbeddingError
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.models import Profile, ProfileEmbedding
from sanket.profiles import service
from sanket.profiles.embedding import EmbedOutcome, embed_profile, embed_profiles
from sanket.profiles.store import ProfileRow, mark_embedding
from sanket.profiles.text import profile_embedding_hash
from tests.index_helpers import SPEC
from tests.match_helpers import OWNER, ScriptedQueryClient, add_profile, profile_body


def fetch(engine: Engine, profile_id: int) -> ProfileRow:
    return service.get(OWNER, profile_id, engine)


def stored(engine: Engine, profile_id: int) -> list[tuple[str, str, str]]:
    stmt = select(
        ProfileEmbedding.model_name, ProfileEmbedding.model_version, ProfileEmbedding.content_hash
    ).where(ProfileEmbedding.profile_id == profile_id)
    with engine.connect() as conn:
        return [(r[0], r[1], r[2]) for r in conn.execute(stmt)]


def test_embedding_stores_the_vector_marks_the_profile_ready_and_uses_the_query_task(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)
    client = FakeEmbeddingClient()

    result = embed_profile(profile.id, client, SPEC, db_engine=clean_db)

    expected = profile_embedding_hash(profile.search_text, SPEC.model_name, "1", SPEC.dimensions)
    assert result.outcome is EmbedOutcome.EMBEDDED
    assert (result.profile_hash, result.embedding_hash) == (profile.content_hash, expected)
    assert stored(clean_db, profile.id) == [(SPEC.model_name, SPEC.model_version, expected)]
    assert fetch(clean_db, profile.id).embedding_status == "ready"
    assert client.query_calls == [profile.search_text]
    assert client.document_calls == []


def test_an_unchanged_profile_is_not_embedded_again(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    client = FakeEmbeddingClient()

    result = embed_profile(profile.id, client, SPEC, db_engine=clean_db)

    assert result.outcome is EmbedOutcome.UNCHANGED
    assert client.query_calls == []


def test_an_unchanged_embedding_still_repairs_a_status_that_lagged(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    with clean_db.begin() as conn:
        mark_embedding(conn, profile.id, profile.content_hash, "pending")

    embed_profile(profile.id, FakeEmbeddingClient(), SPEC, db_engine=clean_db)

    assert fetch(clean_db, profile.id).embedding_status == "ready"


def test_a_rename_does_not_re_embed_but_new_criteria_do(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    before = stored(clean_db, profile.id)
    client = FakeEmbeddingClient()

    service.replace(OWNER, profile.id, profile_body(name="Renamed"), queue=None, db_engine=clean_db)
    embed_profile(profile.id, client, SPEC, db_engine=clean_db)
    assert client.query_calls == []

    service.replace(
        OWNER,
        profile.id,
        profile_body(name="Renamed", summary="data engineering"),
        queue=None,
        db_engine=clean_db,
    )
    assert fetch(clean_db, profile.id).embedding_status == "pending"
    embed_profile(profile.id, client, SPEC, db_engine=clean_db)

    assert len(client.query_calls) == 1
    assert stored(clean_db, profile.id) != before
    assert fetch(clean_db, profile.id).embedding_status == "ready"


def test_a_new_model_version_adds_an_embedding_next_to_the_old_one(clean_db: Engine) -> None:
    profile = add_profile(clean_db)
    v2 = replace(SPEC, model_version="2")
    client = FakeEmbeddingClient(model_version="2")

    embed_profile(profile.id, client, v2, db_engine=clean_db)

    assert sorted(version for _, version, _ in stored(clean_db, profile.id)) == ["1", "2"]


def test_a_missing_profile_is_reported_not_raised(clean_db: Engine) -> None:
    client = FakeEmbeddingClient()

    result = embed_profile(999, client, SPEC, db_engine=clean_db)

    assert result.outcome is EmbedOutcome.MISSING
    assert client.query_calls == []


# --- outages ------------------------------------------------------------------------------


def test_a_provider_outage_leaves_the_profile_pending_until_the_last_attempt(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)
    client = ScriptedQueryClient(error=EmbeddingError("quota", retryable=True))

    with pytest.raises(EmbeddingError):
        embed_profile(profile.id, client, SPEC, final_attempt=False, db_engine=clean_db)

    row = fetch(clean_db, profile.id)
    assert row.embedding_status == "pending"
    assert row.embedding_error is not None and "quota" in row.embedding_error
    assert stored(clean_db, profile.id) == []


def test_the_final_attempt_marks_the_profile_failed_and_a_later_success_recovers_it(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)
    broken = ScriptedQueryClient(error=EmbeddingError("provider down"))

    with pytest.raises(EmbeddingError):
        embed_profile(profile.id, broken, SPEC, final_attempt=True, db_engine=clean_db)
    assert fetch(clean_db, profile.id).embedding_status == "failed"

    embed_profile(profile.id, FakeEmbeddingClient(), SPEC, db_engine=clean_db)

    row = fetch(clean_db, profile.id)
    assert (row.embedding_status, row.embedding_error) == ("ready", None)


def test_input_the_provider_rejects_fails_the_profile_at_once(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    client = ScriptedQueryClient(error=EmbeddingError("bad input", retryable=False))

    with pytest.raises(EmbeddingError):
        embed_profile(profile.id, client, SPEC, final_attempt=False, db_engine=clean_db)

    assert fetch(clean_db, profile.id).embedding_status == "failed"


def test_a_vector_of_the_wrong_width_is_a_failure_not_a_stored_embedding(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)
    client = ScriptedQueryClient(dimensions=8)

    with pytest.raises(EmbeddingError):
        embed_profile(profile.id, client, SPEC, db_engine=clean_db)

    assert stored(clean_db, profile.id) == []
    assert fetch(clean_db, profile.id).embedding_status == "failed"


# --- races --------------------------------------------------------------------------------


def test_a_save_during_embedding_keeps_the_profile_pending_and_the_next_run_fixes_it(
    clean_db: Engine,
) -> None:
    profile = add_profile(clean_db, embed=False)

    def edit_meanwhile(text: str) -> None:
        service.replace(
            OWNER,
            profile.id,
            profile_body(summary="changed while embedding"),
            queue=None,
            db_engine=clean_db,
        )

    embed_profile(
        profile.id, ScriptedQueryClient(on_query=edit_meanwhile), SPEC, db_engine=clean_db
    )

    assert fetch(clean_db, profile.id).embedding_status == "pending"

    client = FakeEmbeddingClient()
    embed_profile(profile.id, client, SPEC, db_engine=clean_db)

    assert len(client.query_calls) == 1 and "changed while embedding" in client.query_calls[0]
    assert fetch(clean_db, profile.id).embedding_status == "ready"


def test_a_profile_deleted_during_embedding_is_reported_missing(clean_db: Engine) -> None:
    profile = add_profile(clean_db, embed=False)

    def delete_meanwhile(text: str) -> None:
        service.delete(OWNER, profile.id, clean_db)

    result = embed_profile(
        profile.id, ScriptedQueryClient(on_query=delete_meanwhile), SPEC, db_engine=clean_db
    )

    assert result.outcome is EmbedOutcome.MISSING
    with clean_db.connect() as conn:
        assert conn.execute(select(Profile.id)).all() == []


# --- batch --------------------------------------------------------------------------------


def test_the_batch_embeds_each_profile_and_counts_failures_without_stopping(
    clean_db: Engine,
) -> None:
    ok = add_profile(clean_db, name="ok", embed=False)
    bad = add_profile(clean_db, name="bad", summary="poison", embed=False)
    done = add_profile(clean_db, name="done")

    def poison_fails(text: str) -> None:
        if "poison" in text:
            raise EmbeddingError("provider rejected the text")

    client = ScriptedQueryClient(on_query=poison_fails)

    summary = embed_profiles([ok.id, bad.id, done.id, 12345], client, SPEC, clean_db)

    assert (summary.embedded, summary.unchanged, summary.missing, summary.failed) == (1, 1, 1, 1)
    assert fetch(clean_db, ok.id).embedding_status == "ready"
    assert fetch(clean_db, bad.id).embedding_status == "failed"
