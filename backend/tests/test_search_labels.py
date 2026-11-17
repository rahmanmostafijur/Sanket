import json
from pathlib import Path

import pytest

from sanket.search.labels import LabelError, load_labels, parse_labels

FP_A = "fp1:" + "a" * 64
FP_B = "fp1:" + "b" * 64


def line(**overrides: object) -> str:
    data: dict[str, object] = {
        "query": "python backend",
        "relevant": [{"job_ref": FP_A, "grade": 3}, {"job_ref": FP_B, "grade": 1}],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_a_valid_line_is_loaded_with_its_grades_and_notes() -> None:
    (query,) = parse_labels([line(notes="why")])

    assert query.query == "python backend"
    assert query.grades == {FP_A: 3, FP_B: 1}
    assert query.notes == "why"


def test_blank_lines_are_skipped_and_the_query_is_trimmed() -> None:
    queries = parse_labels(["", line(query="  python  "), "   ", line(query="java")])

    assert [q.query for q in queries] == ["python", "java"]


def test_a_query_without_relevant_jobs_is_allowed() -> None:
    (query,) = parse_labels([line(relevant=[])])

    assert query.grades == {}


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "valid dictionary"),
        (line(query=""), "query"),
        (line(query="x" * 201), "query"),
        (line(relevant="nope"), "relevant"),
        (line(extra="no"), "extra"),
        (line(relevant=[{"job_ref": FP_A, "grade": 0}]), "grade"),
        (line(relevant=[{"job_ref": FP_A, "grade": 4}]), "grade"),
        (line(relevant=[{"job_ref": FP_A, "grade": "high"}]), "grade"),
        (line(relevant=[{"job_ref": "42", "grade": 2}]), "fingerprint"),
        (line(relevant=[{"job_ref": "fp1:ABC", "grade": 2}]), "fingerprint"),
        (line(relevant=[{"job_ref": FP_A}]), "grade"),
        (line(relevant=[{"job_ref": FP_A, "grade": 2, "extra": 1}]), "extra"),
        (
            line(relevant=[{"job_ref": FP_A, "grade": 2}, {"job_ref": FP_A, "grade": 3}]),
            "more than once",
        ),
        (json.dumps({"relevant": []}), "query"),
    ],
)
def test_malformed_lines_name_the_line_and_the_problem(text: str, fragment: str) -> None:
    with pytest.raises(LabelError, match=f"file.jsonl:2: .*{fragment}"):
        parse_labels([line(query="fine"), text], "file.jsonl")


def test_a_repeated_query_is_an_error_even_with_different_case() -> None:
    with pytest.raises(LabelError, match="file.jsonl:3: .*repeats line 1"):
        parse_labels([line(query="Python"), "", line(query="python")], "file.jsonl")


def test_an_empty_file_is_an_error() -> None:
    with pytest.raises(LabelError, match="no labelled queries"):
        parse_labels(["", "  "], "file.jsonl")


def test_load_labels_reads_utf8_and_reports_unreadable_files(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(line(query="সফটওয়্যার") + "\r\n" + line(query="malmö") + "\n", encoding="utf-8")

    assert [q.query for q in load_labels(path)] == ["সফটওয়্যার", "malmö"]
    with pytest.raises(LabelError, match="cannot read"):
        load_labels(tmp_path / "missing.jsonl")


def test_a_file_that_is_not_utf8_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(LabelError, match="cannot read"):
        load_labels(path)
