"""The labelling sheet: shape, blank labels, determinism and the no-overwrite guard."""

import csv
from pathlib import Path

from sqlalchemy import Engine

from sanket.search.label_draft import COLUMNS, build_rows, load_queries, main
from tests.search_helpers import add_search_job, index_everything


def seed(engine: Engine) -> dict[str, list[int]]:
    python = [
        add_search_job(engine, title=f"Python Engineer {n}", company=f"PyCo {n}") for n in range(3)
    ]
    other = [
        add_search_job(
            engine, title=f"Pastry Chef {n}", company=f"Bakery {n}", description="<p>Bake.</p>"
        )
        for n in range(4)
    ]
    index_everything(engine)
    return {"python": python, "other": other}


def test_rows_have_the_sheet_columns_and_blank_labels(clean_db: Engine) -> None:
    seed(clean_db)

    rows = build_rows(clean_db, ["python engineer"], hits=2, per_query=3)

    assert len(rows) == 3
    for row in rows:
        assert tuple(row) == COLUMNS
        assert row["job_ref"].startswith("fp1:")
        assert row["grade"] == ""
        assert row["notes"] == ""


def test_text_matches_are_included_and_extras_are_not_matches(clean_db: Engine) -> None:
    jobs = seed(clean_db)

    rows = build_rows(clean_db, ["python engineer"], hits=3, per_query=5)

    ids = [row["job_id"] for row in rows]
    assert set(jobs["python"]) <= set(ids)
    assert len(ids) == len(set(ids)) == 5
    assert set(ids) - set(jobs["python"]) <= set(jobs["other"])


def test_same_seed_gives_the_same_sheet(clean_db: Engine) -> None:
    seed(clean_db)
    queries = ["python engineer", "pastry chef"]

    first = build_rows(clean_db, queries, hits=2, per_query=4, seed=3)
    second = build_rows(clean_db, queries, hits=2, per_query=4, seed=3)

    assert first == second


def test_a_query_with_no_text_match_still_gets_random_jobs(clean_db: Engine) -> None:
    seed(clean_db)

    rows = build_rows(clean_db, ["zzzz nothing matches"], hits=3, per_query=5)

    assert len(rows) == 5


def test_load_queries_skips_blank_lines_and_repeats(tmp_path: Path) -> None:
    path = tmp_path / "queries.txt"
    path.write_text(
        "python engineer\n\n  \npython engineer\nremote data analyst\n", encoding="utf-8"
    )

    assert load_queries(path) == ["python engineer", "remote data analyst"]


def test_main_writes_a_csv_and_refuses_to_overwrite_hand_labels(
    clean_db: Engine, tmp_path: Path
) -> None:
    seed(clean_db)
    queries = tmp_path / "queries.txt"
    queries.write_text("python engineer\n", encoding="utf-8")
    out = tmp_path / "sheet.csv"
    args = ["--out", str(out), "--queries", str(queries), "--hits", "2", "--per-query", "3"]

    assert main(args, clean_db) == 0
    with out.open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert len(written) == 3
    assert tuple(written[0]) == COLUMNS

    out.write_text("query,grade\nkept,3\n", encoding="utf-8")
    assert main(args, clean_db) == 1
    assert out.read_text(encoding="utf-8") == "query,grade\nkept,3\n"

    assert main([*args, "--force"], clean_db) == 0
    with out.open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 3
