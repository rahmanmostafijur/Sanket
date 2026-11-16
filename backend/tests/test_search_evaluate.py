"""The evaluation harness on a seeded synthetic corpus. Metric values are checked for being
well-formed, never for a quality threshold: nothing here tunes or judges the search."""

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine

from sanket.embeddings.fake import FakeEmbeddingClient
from sanket.search import evaluate
from sanket.search.evaluate import find_job_refs, run_evaluation
from sanket.search.labels import load_labels
from sanket.search.report import format_report, report_to_dict
from sanket.search.retrieval import SearchConfig, SearchMode
from tests.eval_corpus import EVAL_JOBS, FINGERPRINTS, seed_eval_corpus
from tests.index_helpers import SPEC
from tests.search_helpers import index_everything

EXAMPLE_FILE = Path(__file__).resolve().parents[1] / "eval" / "queries.example.jsonl"
CFG = SearchConfig(SPEC, candidates=50, rrf_k=60, fulltext_weight=1.0, vector_weight=1.0)
ALL = (SearchMode.HYBRID, SearchMode.TEXT, SearchMode.VECTOR)


class FailingQueryClient(FakeEmbeddingClient):
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("provider down")


def test_the_example_file_loads_and_only_refers_to_the_synthetic_corpus() -> None:
    labels = load_labels(EXAMPLE_FILE)

    assert 5 <= len(labels) <= 8
    refs = {ref for item in labels for ref in item.grades}
    assert refs <= set(FINGERPRINTS.values())
    assert any(not item.grades for item in labels)  # one unlabelled query shows the exclusion


def test_the_corpus_fingerprints_are_distinct() -> None:
    assert len(set(FINGERPRINTS.values())) == len(EVAL_JOBS)


def test_all_three_modes_produce_well_formed_metrics(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    client = index_everything(clean_db)
    labels = load_labels(EXAMPLE_FILE)

    report = run_evaluation(labels, 10, ALL, CFG, client, clean_db)

    assert [mode.mode for mode in report.modes] == list(ALL)
    for mode in report.modes:
        assert len(mode.results) == len(labels)
        assert mode.summary.queries_scored == len(labels) - 1
        assert mode.summary.queries_excluded == 1
        for value in (
            mode.summary.mean_recall,
            mode.summary.mean_precision,
            mode.summary.mean_reciprocal_rank,
            mode.summary.mean_ndcg,
        ):
            assert value is not None
            assert 0.0 <= value <= 1.0
        for result in mode.results:
            assert len(result.ranked) <= 10
            assert result.missing_refs == ()
            assert not result.degraded
            if result.metrics.scored:
                assert result.metrics.ndcg is not None
                assert 0.0 <= result.metrics.ndcg <= 1.0
    # Embeddings are cached: each query is embedded once however many modes use it.
    assert len(client.query_calls) == len(labels)


def test_text_mode_never_calls_the_embedding_provider(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    client = index_everything(clean_db)
    before = len(client.query_calls)

    run_evaluation(load_labels(EXAMPLE_FILE), 5, (SearchMode.TEXT,), CFG, client, clean_db)

    assert len(client.query_calls) == before


def test_a_failing_embedding_is_flagged_not_hidden(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    index_everything(clean_db)
    labels = load_labels(EXAMPLE_FILE)

    report = run_evaluation(labels, 10, (SearchMode.HYBRID,), CFG, FailingQueryClient(), clean_db)

    assert all(result.degraded for result in report.modes[0].results)


def test_labelled_jobs_missing_from_the_database_are_reported(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    client = index_everything(clean_db)
    labels = load_labels(EXAMPLE_FILE)
    ghost = "fp1:" + "0" * 64
    first = labels[0].model_copy(
        update={
            "relevant": [
                *labels[0].relevant,
                labels[0].relevant[0].model_copy(update={"job_ref": ghost}),
            ]
        }
    )

    report = run_evaluation([first], 10, (SearchMode.TEXT,), CFG, client, clean_db)

    (result,) = report.modes[0].results
    assert result.missing_refs == (ghost,)
    assert "not in this database" in format_report(report, "db")


@pytest.mark.parametrize("k", [0, 51])
def test_k_must_be_positive_and_within_the_candidate_depth(clean_db: Engine, k: int) -> None:
    with pytest.raises(ValueError, match="k"):
        run_evaluation(load_labels(EXAMPLE_FILE), k, (SearchMode.TEXT,), CFG, None, clean_db)


def test_the_report_renders_as_a_table_and_as_json(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    client = index_everything(clean_db)
    report = run_evaluation(load_labels(EXAMPLE_FILE), 10, ALL, CFG, client, clean_db)

    text = format_report(report, "127.0.0.1:5433/sanket_test")
    payload = report_to_dict(report, "127.0.0.1:5433/sanket_test")

    for needle in ("hybrid", "text", "vector", "nDCG", "R@10", "mean (scored queries)", "excluded"):
        assert needle in text
    assert "gardening tools" in text
    assert json.loads(json.dumps(payload))["modes"][0]["mode"] == "hybrid"
    assert len(payload["modes"]) == 3


def test_find_lists_fingerprints_for_labelling(clean_db: Engine) -> None:
    seed_eval_corpus(clean_db)
    index_everything(clean_db)

    refs = find_job_refs("kubernetes", clean_db)

    assert {ref.fingerprint for ref in refs} == {FINGERPRINTS["devops"], FINGERPRINTS["go_backend"]}
    assert {ref.company for ref in refs} == {"Cloudy Co", "Gopher Works"}


def test_the_cli_writes_a_json_report_in_text_mode(
    clean_db: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_eval_corpus(clean_db)
    index_everything(clean_db)
    monkeypatch.setattr(evaluate, "engine", clean_db)
    out = tmp_path / "report.json"

    code = evaluate.main(
        ["--queries", str(EXAMPLE_FILE), "--mode", "text", "--k", "5", "--json", str(out)]
    )

    assert code == 0
    assert "mean (scored queries)" in capsys.readouterr().out
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["k"] == 5
    assert saved["modes"][0]["mode"] == "text"
    assert "password" not in saved["database"].lower()


def test_the_cli_reports_a_malformed_file_and_a_missing_key(
    clean_db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"query": ""}\n', encoding="utf-8")
    monkeypatch.setattr(evaluate, "engine", clean_db)
    monkeypatch.setattr(evaluate, "query_embedding_client", lambda config: None)

    with pytest.raises(SystemExit, match="bad.jsonl:1"):
        evaluate.main(["--queries", str(bad)])
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        evaluate.main(["--queries", str(EXAMPLE_FILE), "--mode", "vector"])
    with pytest.raises(SystemExit, match="--queries"):
        evaluate.main([])


def test_the_cli_find_option_prints_fingerprints(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_eval_corpus(clean_db)
    index_everything(clean_db)
    monkeypatch.setattr(evaluate, "engine", clean_db)

    assert evaluate.main(["--find", "nurse"]) == 0

    assert FINGERPRINTS["nurse"] in capsys.readouterr().out
