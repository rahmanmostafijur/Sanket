"""Filters applied inside the candidate queries (the HTTP layer is tested separately)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from sanket.extraction.schema import SCHEMA_VERSION
from sanket.indexing.filters import SearchFilters
from sanket.indexing.queries import fulltext_candidates, vector_candidates
from tests.factories import add_extraction
from tests.index_helpers import (
    SPEC,
    add_indexable_job,
    representative_posting_id,
    set_posting_count,
)
from tests.search_helpers import (
    add_search_job,
    extraction_data,
    index_everything,
    seed_filter_corpus,
)


def text_ids(engine: Engine, filters: SearchFilters, query: str = "engineer") -> set[int]:
    return {c.job_id for c in fulltext_candidates(query, 50, engine, filters=filters)}


def vector_ids(engine: Engine, client_query: list[float], filters: SearchFilters) -> set[int]:
    result = vector_candidates(client_query, SPEC, 50, db_engine=engine, filters=filters)
    return {c.job_id for c in result}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (SearchFilters(work_modes=("remote",)), {"remote_senior"}),
        (SearchFilters(work_modes=("remote", "hybrid")), {"remote_senior", "hybrid_junior"}),
        (SearchFilters(seniorities=("lead",)), {"onsite_lead"}),
        (
            SearchFilters(employment_types=("part_time", "contract")),
            {"hybrid_junior", "onsite_lead"},
        ),
        (SearchFilters(countries=("SE",)), {"hybrid_junior"}),
        (SearchFilters(sources=("lever",)), {"hybrid_junior"}),
        (SearchFilters(sources=("lever", "remoteok")), {"hybrid_junior", "onsite_lead"}),
        (SearchFilters(company="acme"), {"remote_senior"}),
        (SearchFilters(company="  ZETA corp "), {"hybrid_junior"}),
        (SearchFilters(location="stockholm"), {"hybrid_junior"}),
        (
            SearchFilters(posted_after=datetime(2026, 9, 15, tzinfo=UTC)),
            {
                "remote_senior",
                "hybrid_junior",
                "no_extraction",
            },
        ),
        (SearchFilters(skills=("python",)), {"remote_senior", "hybrid_junior"}),
        (SearchFilters(skills=("PYTHON", "go")), {"remote_senior"}),
        (SearchFilters(skills=("python", "cobol")), set()),
        (
            SearchFilters(work_modes=("remote", "hybrid"), skills=("rust",)),
            {"hybrid_junior"},
        ),
        (SearchFilters(work_modes=("remote",), countries=("SE",)), set()),
        (SearchFilters(), {"remote_senior", "hybrid_junior", "onsite_lead", "no_extraction"}),
    ],
)
def test_each_filter_narrows_both_candidate_queries(
    clean_db: Engine, filters: SearchFilters, expected: set[str]
) -> None:
    jobs = seed_filter_corpus(clean_db)
    client = index_everything(clean_db)
    wanted = {jobs[name] for name in expected}

    assert text_ids(clean_db, filters) == wanted
    assert vector_ids(clean_db, client.embed_query("engineer"), filters) == wanted


def test_location_filter_treats_like_wildcards_literally(clean_db: Engine) -> None:
    percent = add_search_job(clean_db, title="Engineer A", location="Remote 100% anywhere")
    underscore = add_search_job(clean_db, title="Engineer B", location="Remote_EU")
    plain = add_search_job(clean_db, title="Engineer C", location="Remote EU")
    index_everything(clean_db)

    assert text_ids(clean_db, SearchFilters(location="100%")) == {percent}
    assert text_ids(clean_db, SearchFilters(location="remote_eu")) == {underscore}
    assert text_ids(clean_db, SearchFilters(location="%")) == {percent}
    assert text_ids(clean_db, SearchFilters(location="_")) == {underscore}
    assert plain not in text_ids(clean_db, SearchFilters(location="_eu"))


@pytest.mark.parametrize("hostile", ["x' OR '1'='1", "'; DROP TABLE job; --", "\\", '"'])
def test_hostile_filter_values_are_plain_values(clean_db: Engine, hostile: str) -> None:
    add_search_job(clean_db, title="Engineer", extraction=extraction_data())
    index_everything(clean_db)

    for filters in (
        SearchFilters(company=hostile),
        SearchFilters(location=hostile),
        SearchFilters(skills=(hostile,)),
        SearchFilters(sources=(hostile,)),
        SearchFilters(work_modes=(hostile,)),
        SearchFilters(countries=(hostile,)),
    ):
        assert text_ids(clean_db, filters) == set()
    assert len(text_ids(clean_db, SearchFilters())) == 1


def test_posted_after_falls_back_to_first_seen_when_the_posting_has_no_date(
    clean_db: Engine,
) -> None:
    undated = add_search_job(clean_db, title="Engineer Undated")
    index_everything(clean_db)

    assert text_ids(clean_db, SearchFilters(posted_after=datetime(2000, 1, 1, tzinfo=UTC))) == {
        undated
    }
    assert text_ids(clean_db, SearchFilters(posted_after=datetime(2999, 1, 1, tzinfo=UTC))) == set()


def test_filters_use_the_newest_successful_extraction_only(clean_db: Engine) -> None:
    job_id = add_search_job(
        clean_db, title="Engineer", extraction=extraction_data(work_mode="onsite")
    )
    add_extraction(
        clean_db,
        representative_posting_id(clean_db, job_id),
        schema_version=SCHEMA_VERSION + 1,
        data=extraction_data(work_mode="remote"),
    )
    index_everything(clean_db)

    assert text_ids(clean_db, SearchFilters(work_modes=("remote",))) == {job_id}
    assert text_ids(clean_db, SearchFilters(work_modes=("onsite",))) == set()


def test_a_failed_extraction_never_matches_extraction_filters(clean_db: Engine) -> None:
    job_id = add_search_job(clean_db, title="Engineer")
    add_extraction(clean_db, representative_posting_id(clean_db, job_id), status="failed")
    index_everything(clean_db)

    assert text_ids(clean_db, SearchFilters(work_modes=("remote",))) == set()
    assert text_ids(clean_db, SearchFilters()) == {job_id}


def test_filters_are_applied_inside_the_query_so_results_are_not_starved(
    clean_db: Engine,
) -> None:
    # 30 strong text matches fail the filter; the only job that passes matches weakly. A
    # post-filter over the top 5 would return nothing.
    for n in range(30):
        add_search_job(
            clean_db,
            title="Python Python Python Developer",
            extraction=extraction_data(work_mode="onsite"),
            description=f"<p>Python {n}</p>",
        )
    weak = add_search_job(
        clean_db,
        title="Office Clerk",
        description="<p>python once</p>",
        extraction=extraction_data(work_mode="remote"),
    )
    client = index_everything(clean_db)
    filters = SearchFilters(work_modes=("remote",))

    by_text = fulltext_candidates("python", 5, clean_db, filters=filters)
    by_vector = vector_candidates(
        client.embed_query("python developer"), SPEC, 5, db_engine=clean_db, filters=filters
    )

    assert [c.job_id for c in by_text] == [weak]
    assert [c.job_id for c in by_vector] == [weak]


def test_dead_jobs_are_excluded_from_both_queries_even_before_the_worker_runs(
    clean_db: Engine,
) -> None:
    dead = add_indexable_job(clean_db, title="Engineer Dead")
    alive = add_indexable_job(clean_db, title="Engineer Alive")
    client = index_everything(clean_db)
    set_posting_count(clean_db, dead, 0)

    both = vector_candidates(
        client.embed_query("engineer"), SPEC, 10, db_engine=clean_db, filters=SearchFilters()
    )

    assert [c.job_id for c in both] == [alive]
    assert text_ids(clean_db, SearchFilters()) == {alive}
