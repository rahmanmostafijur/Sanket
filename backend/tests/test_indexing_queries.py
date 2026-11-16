from typing import Any

import pytest
from sqlalchemy import ClauseElement, Engine, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import Executable

from sanket.embeddings.client import EmbeddingSpec
from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.indexing.queries import (
    MAX_EF_SEARCH,
    fulltext_candidates,
    fulltext_statement,
    vector_candidates,
    vector_statement,
)
from sanket.indexing.service import index_pending
from tests.index_helpers import (
    CFG,
    SPEC,
    add_indexable_job,
    insert_embedding_row,
    set_posting_count,
)


class Explain(Executable, ClauseElement):
    inherit_cache = False

    def __init__(self, statement: Any) -> None:
        self.statement = statement


@compiles(Explain)
def _compile_explain(element: Explain, compiler: Any, **kw: Any) -> str:
    return "EXPLAIN " + compiler.process(element.statement, **kw)


def index_all(engine: Engine) -> FakeEmbeddingClient:
    client = FakeEmbeddingClient(model_name=SPEC.model_name, model_version=SPEC.model_version)
    index_pending(CFG, client, apply=True, db_engine=engine)
    return client


def plan(engine: Engine, statement: Any) -> str:
    """The query plan with sequential scans disabled, so an index shows up if it can be used."""
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        return "\n".join(row[0] for row in conn.execute(Explain(statement)))


# --- full text ---------------------------------------------------------------------------


def test_fulltext_finds_the_matching_job_only(clean_db: Engine) -> None:
    wanted = add_indexable_job(clean_db, title="Plumber", description="<p>Fix leaking pipes.</p>")
    add_indexable_job(clean_db, title="Data Analyst", description="<p>Dashboards.</p>")
    index_all(clean_db)

    result = fulltext_candidates("plumber", 10, clean_db)

    assert [(c.job_id, c.rank) for c in result] == [(wanted, 1)]
    assert result[0].score > 0


def test_title_match_outranks_description_match(clean_db: Engine) -> None:
    in_description = add_indexable_job(
        clean_db, title="Office Manager", description="<p>Some python scripting helps.</p>"
    )
    in_title = add_indexable_job(clean_db, title="Python Developer", description="<p>Code.</p>")
    index_all(clean_db)

    result = fulltext_candidates("python", 10, clean_db)

    assert [c.job_id for c in result] == [in_title, in_description]
    assert [c.rank for c in result] == [1, 2]
    assert result[0].score > result[1].score


def test_fulltext_matches_company_and_location_text(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db, company="Zebra Systems", location="Oslo")
    add_indexable_job(clean_db, title="Data Analyst")
    index_all(clean_db)

    assert [c.job_id for c in fulltext_candidates("zebra oslo", 10, clean_db)] == [job_id]


@pytest.mark.parametrize(
    ("title", "description", "query"),
    [
        ("Systemutvecklare", "<p>Vi söker en utvecklare i Malmö.</p>", "malmö"),
        ("ডেভেলপার", "<p>আমরা একজন সফটওয়্যার ইঞ্জিনিয়ার খুঁজছি</p>", "সফটওয়্যার"),
        ("Ingeniør", "<p>Stilling i Tromsø.</p>", "tromsø"),
    ],
)
def test_fulltext_works_for_non_english_text(
    clean_db: Engine, title: str, description: str, query: str
) -> None:
    job_id = add_indexable_job(clean_db, title=title, description=description)
    add_indexable_job(clean_db, title="Data Analyst", description="<p>Dashboards.</p>")
    index_all(clean_db)

    assert [c.job_id for c in fulltext_candidates(query, 10, clean_db)] == [job_id]


def test_websearch_syntax_phrases_and_exclusions(clean_db: Engine) -> None:
    both = add_indexable_job(clean_db, title="Backend Engineer", description="<p>Go and Rust.</p>")
    only_go = add_indexable_job(clean_db, title="Backend Developer", description="<p>Go only.</p>")
    index_all(clean_db)

    assert {c.job_id for c in fulltext_candidates("backend go", 10, clean_db)} == {both, only_go}
    assert [c.job_id for c in fulltext_candidates('"backend engineer"', 10, clean_db)] == [both]
    assert [c.job_id for c in fulltext_candidates("backend -rust", 10, clean_db)] == [only_go]
    assert {c.job_id for c in fulltext_candidates("rust or developer", 10, clean_db)} == {
        both,
        only_go,
    }


@pytest.mark.parametrize(
    "hostile",
    ["'); DROP TABLE job; --", "a' OR '1'='1", "!!! ((", "\\", "&|!:*", "'", '"'],
)
def test_hostile_query_text_is_harmless(clean_db: Engine, hostile: str) -> None:
    add_indexable_job(clean_db)
    index_all(clean_db)

    assert fulltext_candidates(hostile, 10, clean_db) == []
    assert len(fulltext_candidates("backend", 10, clean_db)) == 1


def test_blank_query_and_bad_limit_return_nothing(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    index_all(clean_db)

    assert fulltext_candidates("   ", 10, clean_db) == []
    assert fulltext_candidates("backend", 0, clean_db) == []


def test_fulltext_limit_and_dead_jobs(clean_db: Engine) -> None:
    ids = [add_indexable_job(clean_db, title=f"Python Developer {n}") for n in range(4)]
    index_all(clean_db)
    set_posting_count(clean_db, ids[0], 0)  # dead, but the worker has not cleaned it yet

    result = fulltext_candidates("python", 2, clean_db)

    assert len(result) == 2
    assert ids[0] not in {c.job_id for c in result}


def test_unindexed_jobs_are_not_found(clean_db: Engine) -> None:
    add_indexable_job(clean_db, title="Plumber")

    assert fulltext_candidates("plumber", 10, clean_db) == []


def test_fulltext_query_can_use_the_gin_index(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    index_all(clean_db)

    assert "ix_job_search_vector" in plan(clean_db, fulltext_statement("backend", 10))


# --- vectors -----------------------------------------------------------------------------


def test_nearest_job_comes_first(clean_db: Engine) -> None:
    python = add_indexable_job(
        clean_db, title="Python Developer", description="<p>Python Django backend services.</p>"
    )
    chef = add_indexable_job(
        clean_db, title="Pastry Chef", company="Bakery", description="<p>Bread and cakes.</p>"
    )
    nurse = add_indexable_job(
        clean_db, title="Nurse", company="Clinic", description="<p>Patient care.</p>"
    )
    client = index_all(clean_db)

    result = vector_candidates(
        client.embed_query("python backend developer"), SPEC, 3, db_engine=clean_db
    )

    assert result[0].job_id == python
    assert {c.job_id for c in result} == {python, chef, nurse}
    assert [c.rank for c in result] == [1, 2, 3]
    assert result[0].score < result[1].score <= result[2].score


def test_the_same_text_as_a_job_is_at_distance_zero(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    client = index_all(clean_db)
    stored_text = client.document_calls[0][0]

    (best,) = vector_candidates(client.embed_query(stored_text), SPEC, 1, db_engine=clean_db)

    assert best.score == pytest.approx(0.0, abs=1e-6)


def test_vector_search_only_sees_the_requested_model_version(clean_db: Engine) -> None:
    job_id = add_indexable_job(clean_db)
    other = add_indexable_job(clean_db, title="Pastry Chef")
    client = index_all(clean_db)
    insert_embedding_row(clean_db, other, "old-version")
    query = client.embed_query("pastry chef")
    old_spec = EmbeddingSpec(SPEC.model_name, "old-version", SPEC.dimensions)

    current = vector_candidates(query, SPEC, 10, db_engine=clean_db)
    old = vector_candidates(query, old_spec, 10, db_engine=clean_db)

    assert {c.job_id for c in current} == {job_id, other}
    assert [c.job_id for c in old] == [other]


def test_vector_limit_and_ef_search_are_applied(clean_db: Engine) -> None:
    for n in range(5):
        add_indexable_job(clean_db, title=f"Engineer {n}")
    client = index_all(clean_db)
    query = client.embed_query("engineer")

    assert len(vector_candidates(query, SPEC, 2, ef_search=1, db_engine=clean_db)) == 2
    assert len(vector_candidates(query, SPEC, 10, ef_search=5000, db_engine=clean_db)) == 5
    assert vector_candidates(query, SPEC, 0, db_engine=clean_db) == []
    assert MAX_EF_SEARCH == 1000


def test_ef_search_setting_does_not_leak_out_of_the_query(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    client = index_all(clean_db)
    before = _show(clean_db, "hnsw.ef_search")

    vector_candidates(client.embed_query("x"), SPEC, 1, ef_search=7, db_engine=clean_db)

    assert _show(clean_db, "hnsw.ef_search") == before


def _show(engine: Engine, name: str) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text(f"SHOW {name}")).scalar_one())


def test_query_vector_of_the_wrong_width_is_rejected(clean_db: Engine) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        vector_candidates([0.1, 0.2], SPEC, 5, db_engine=clean_db)


def test_nearest_neighbour_query_shape_can_use_the_hnsw_index(clean_db: Engine) -> None:
    add_indexable_job(clean_db)
    client = index_all(clean_db)

    statement = vector_statement(client.embed_query("backend"), 5)

    assert "ix_job_embedding_embedding_hnsw" in plan(clean_db, statement)
