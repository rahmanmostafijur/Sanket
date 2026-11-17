"""The whole backend pipeline, end to end, from recorded payloads to API answers.

ingest (two sources) -> canonicalise -> extract (scripted model) -> index (full text and
embeddings) -> profile saved and embedded -> matching -> /search and /profiles/{id}/matches.
Everything is real except the edges (HTTP, LLM, embeddings, Redis); see `pipeline.py` for the
steps, and for the extension points where the live feed and authentication are added.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sanket.extraction.runner import Outcome
from sanket.ingest import STATUS_OK
from sanket.matching.notify import MatchRecord
from sanket.models import MatchStatus
from tests.e2e import data
from tests.e2e import pipeline as p
from tests.match_helpers import RecordingNotifier


@pytest.fixture
def stack(clean_db: Engine) -> p.Stack:
    return p.build_stack(clean_db)


@pytest.fixture
def client(stack: p.Stack) -> TestClient:
    return p.api_client(stack)


@pytest.fixture
def first_run(stack: p.Stack) -> p.PipelineRun:
    return p.run_pipeline(stack, data.first_run_feeds())


def recorded(stack: p.Stack) -> list[MatchRecord]:
    assert isinstance(stack.notifier, RecordingNotifier)
    return stack.notifier.records


def by_title(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["job"]["title"]: item for item in items}


# -- postings become indexed jobs ----------------------------------------------------------------


def test_the_first_run_turns_two_sources_into_indexed_jobs(
    stack: p.Stack, first_run: p.PipelineRun
) -> None:
    assert [(s.name, s.status, s.new) for s in first_run.ingested] == [
        ("greenhouse", STATUS_OK, 3),
        ("remotive", STATUS_OK, 3),
    ]
    assert first_run.canonical.jobs_created == data.FIRST_RUN_JOBS
    assert p.job_titles_by_posting_count(stack.engine) == {
        data.BACKEND: 2,  # listed by both sources, one job
        data.DATA_SCIENTIST: 1,
        data.FRONTEND: 1,
        data.DEVOPS: 1,
        data.OFFICE: 1,
    }
    assert first_run.extraction == {Outcome.OK: data.FIRST_RUN_POSTINGS}
    assert stack.llm.calls == data.FIRST_RUN_POSTINGS
    assert first_run.indexing.embedded == data.FIRST_RUN_JOBS
    assert p.index_state(stack.engine) == p.IndexState(
        jobs=5, with_search_vector=5, embeddings=5, live_jobs=5
    )
    # Indexing queued one matching task per embedded job (no profile exists yet).
    assert first_run.tasks_run == data.FIRST_RUN_JOBS


# -- search --------------------------------------------------------------------------------------


def test_search_finds_the_job_that_says_what_was_asked_for(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    body = p.search(client, "kubernetes")

    assert body["degraded"] is False
    top = body["items"][0]
    assert top["title"] == data.DEVOPS
    assert top["company"] == "Beta Corp"
    assert top["source"] == "remotive"
    assert top["url"] == "https://remotive.com/remote-jobs/devops/python-devops-engineer-8002"
    assert top["matched_by"] == "both"
    assert top["extracted"]["skills"] == ["Python", "Kubernetes"]
    assert top["salary_text"] == "$70k-$90k"


def test_a_job_listed_by_two_sources_is_one_search_result_with_both_sources(
    client: TestClient, first_run: p.PipelineRun
) -> None:
    items = p.search(client, "postgresql apis")["items"]

    backend = [item for item in items if item["title"] == data.BACKEND]
    assert len(backend) == 1
    assert {s["source"] for s in backend[0]["sources"]} == {"greenhouse", "remotive"}
    assert items[0]["title"] == data.BACKEND


def test_search_filters_narrow_the_candidates_not_just_the_page(
    client: TestClient, first_run: p.PipelineRun
) -> None:
    assert p.search_titles(client, "engineer scientist", work_mode="hybrid") == [
        data.DATA_SCIENTIST
    ]
    assert p.search_titles(client, "python", work_mode="onsite") == [data.OFFICE]
    assert set(p.search_titles(client, "python engineer", source="greenhouse")) <= {
        data.BACKEND,
        data.DATA_SCIENTIST,
        data.FRONTEND,
    }
    assert p.search_titles(client, "python", skills=["Kubernetes"]) == [data.DEVOPS]


# -- profile, embedding and matching -------------------------------------------------------------


def test_a_new_profile_is_embedded_and_matched_against_the_indexed_jobs(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    profile = p.create_profile(client, data.PROFILE_BODY)
    assert profile["embedding_status"] == "pending"

    assert p.drain_queue(stack) == 2  # embed the profile, then match it

    assert client.get(f"/profiles/{profile['id']}").json()["embedding_status"] == "ready"
    matches = p.matches_of(client, profile["id"])
    assert sorted(m["job"]["title"] for m in matches) == data.EXPECTED_FIRST_MATCHES
    for match in matches:
        assert match["status"] == "active"
        assert 0.0 <= match["score"] <= 1.0
        assert match["components"]["filters"]["work_mode"] == "pass"
        assert match["job"]["url"] and match["job"]["attribution"]
    assert [m["id"] for m in matches] == sorted(m["id"] for m in matches)
    # Delivered once each, with the owner and the persisted ids.
    assert sorted(r.match_id for r in recorded(stack)) == [m["id"] for m in matches]
    assert {r.owner_id for r in recorded(stack)} == {p.OWNER}
    assert all(row[6] is not None for row in p.match_snapshot(stack.engine))


def test_a_profile_saved_before_the_jobs_exist_is_matched_by_the_indexing_run(
    stack: p.Stack, client: TestClient
) -> None:
    profile = p.create_profile(client, data.PROFILE_BODY)
    p.drain_queue(stack)
    assert p.matches_of(client, profile["id"]) == []

    run = p.run_pipeline(stack, data.first_run_feeds())

    assert run.tasks_run == data.FIRST_RUN_JOBS
    assert p.matched_titles(client, profile["id"]) == data.EXPECTED_FIRST_MATCHES
    assert len(recorded(stack)) == len(data.EXPECTED_FIRST_MATCHES)


def test_the_profile_filters_decide_who_matches(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    strict = p.create_profile(
        client, {**data.PROFILE_BODY, "name": "Strict", "required_skills": ["Python", "Kubernetes"]}
    )
    hybrid = p.create_profile(
        client, {**data.PROFILE_BODY, "name": "Hybrid", "work_modes": ["hybrid"]}
    )
    p.drain_queue(stack)

    assert p.matched_titles(client, strict["id"]) == [data.DEVOPS]
    assert p.matched_titles(client, hybrid["id"]) == [data.DATA_SCIENTIST]


# -- reruns and changes --------------------------------------------------------------------------


def test_running_the_pipeline_again_changes_nothing(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    profile = p.create_profile(client, data.PROFILE_BODY)
    p.drain_queue(stack)
    before = p.match_snapshot(stack.engine)
    delivered = len(recorded(stack))
    llm_calls = stack.llm.calls
    embedded_texts = stack.embedder.texts_embedded

    rerun = p.run_pipeline(stack, data.first_run_feeds())

    assert [(s.new, s.updated, s.unchanged) for s in rerun.ingested] == [(0, 0, 3), (0, 0, 3)]
    # Re-seen postings only move the jobs' seen-times (resynced); nothing is linked or created.
    canonical = rerun.canonical
    assert (canonical.linked, canonical.moved, canonical.unlinked, canonical.jobs_created) == (
        0,
        0,
        0,
        0,
    )
    assert canonical.unchanged == data.FIRST_RUN_POSTINGS
    assert rerun.extraction == {}
    assert rerun.indexing.embedded == 0 and rerun.indexing.unchanged == data.FIRST_RUN_JOBS
    assert rerun.tasks_run == 0
    assert stack.llm.calls == llm_calls
    assert stack.embedder.texts_embedded == embedded_texts
    assert p.match_snapshot(stack.engine) == before
    assert len(recorded(stack)) == delivered
    assert p.matched_titles(client, profile["id"]) == data.EXPECTED_FIRST_MATCHES


def test_a_new_listing_that_fits_is_matched_once_it_is_indexed(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    profile = p.create_profile(client, data.PROFILE_BODY)
    p.drain_queue(stack)
    first = {m["job"]["title"]: m["id"] for m in p.matches_of(client, profile["id"])}

    run = p.run_pipeline(stack, data.second_run_feeds())

    assert run.ingested[1].new == 1
    assert run.extraction == {Outcome.OK: 1}
    assert run.indexing.embedded == 1
    assert p.search_titles(client, "python platform team")[0] == data.STAFF
    after = by_title(p.matches_of(client, profile["id"]))
    assert sorted(after) == sorted([*data.EXPECTED_FIRST_MATCHES, data.STAFF])
    assert {title: after[title]["id"] for title in first} == first  # ids are stable
    assert after[data.STAFF]["id"] > max(first.values())
    assert [r.job_id for r in recorded(stack)][-1] == after[data.STAFF]["job_id"]
    assert len(recorded(stack)) == 3


def test_a_listing_taken_down_withdraws_its_match_and_leaves_the_index(
    stack: p.Stack, client: TestClient, first_run: p.PipelineRun
) -> None:
    profile = p.create_profile(client, data.PROFILE_BODY)
    p.drain_queue(stack)
    held = by_title(p.matches_of(client, profile["id"]))

    # One of the two postings of the backend job goes: the job lives on, the match stays.
    p.remove_posting(stack.engine, "remotive", "8001")
    p.run_pipeline(stack, [])
    assert p.job_titles_by_posting_count(stack.engine)[data.BACKEND] == 1
    assert p.matched_titles(client, profile["id"]) == data.EXPECTED_FIRST_MATCHES

    # The only posting of the DevOps job goes: the job dies and so does its match.
    p.remove_posting(stack.engine, "remotive", "8002")
    run = p.run_pipeline(stack, [])

    assert run.canonical.jobs_resynced == 1
    assert run.indexing.removed == 1
    assert run.tasks_run == 1
    assert p.matched_titles(client, profile["id"]) == [data.BACKEND]
    history = {m["job_id"]: m for m in p.matches_of(client, profile["id"], include_withdrawn=True)}
    devops_id = held[data.DEVOPS]["job_id"]
    assert history[devops_id]["status"] == MatchStatus.WITHDRAWN
    assert history[devops_id]["id"] == held[data.DEVOPS]["id"]  # same row, not a new match
    assert data.DEVOPS not in p.search_titles(client, "kubernetes")
    assert p.index_state(stack.engine).embeddings == data.FIRST_RUN_JOBS - 1
