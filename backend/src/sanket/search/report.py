"""Text and JSON renderings of an evaluation report."""

from typing import TYPE_CHECKING, Any

from sanket.search.metrics import Aggregate

if TYPE_CHECKING:
    from sanket.search.evaluate import EvalReport, ModeReport, QueryResult

QUERY_WIDTH = 34
CELL_WIDTH = 6
NOT_SCORED = "-"
DEGRADED_MARK = "!"


def _cell(value: float | None) -> str:
    return (NOT_SCORED if value is None else f"{value:.3f}").rjust(CELL_WIDTH)


def _metric_cells(result: "QueryResult") -> str:
    metrics = result.metrics
    return " ".join(
        _cell(value)
        for value in (metrics.recall, metrics.precision, metrics.reciprocal_rank, metrics.ndcg)
    )


def _mean_cells(summary: Aggregate) -> str:
    return " ".join(
        _cell(value)
        for value in (
            summary.mean_recall,
            summary.mean_precision,
            summary.mean_reciprocal_rank,
            summary.mean_ndcg,
        )
    )


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "~"


def _header(report: "EvalReport") -> list[str]:
    k = report.k
    labels = ["R@" + str(k), "P@" + str(k), "RR", "nDCG"]
    columns = " ".join(label.rjust(CELL_WIDTH) for label in labels)
    top = f"{'query':<{QUERY_WIDTH}} {'rel':>3}"
    mode_titles = " | ".join(
        report_mode.mode.value.center(len(columns)) for report_mode in report.modes
    )
    sub = f"{'':<{QUERY_WIDTH}} {'':>3} " + " | ".join(columns for _ in report.modes)
    return [f"{top} {mode_titles}", sub]


def _query_rows(report: "EvalReport") -> list[str]:
    rows = []
    first = report.modes[0]
    for index, result in enumerate(first.results):
        cells = []
        marks = ""
        for mode_report in report.modes:
            item = mode_report.results[index]
            cells.append(_metric_cells(item))
            marks += DEGRADED_MARK if item.degraded else ""
        name = _truncate(result.query, QUERY_WIDTH - len(marks) - (1 if marks else 0))
        label = f"{name}{' ' + marks if marks else ''}"
        rel = str(result.metrics.relevant_count)
        rows.append(f"{label:<{QUERY_WIDTH}} {rel:>3} " + " | ".join(cells))
    return rows


def _mean_row(report: "EvalReport") -> str:
    cells = " | ".join(_mean_cells(mode.summary) for mode in report.modes)
    return f"{'mean (scored queries)':<{QUERY_WIDTH}} {'':>3} {cells}"


def _notes(report: "EvalReport") -> list[str]:
    notes = []
    for mode in report.modes:
        summary = mode.summary
        notes.append(
            f"{mode.mode.value}: {summary.queries_scored} queries scored, "
            f"{summary.queries_excluded} excluded (no relevant jobs); MRR = "
            f"{'-' if summary.mean_reciprocal_rank is None else f'{summary.mean_reciprocal_rank:.3f}'}"
        )
    first = report.modes[0].results
    missing = sum(len(result.missing_refs) for result in first)
    if missing:
        notes.append(
            f"WARNING: {missing} labelled job reference(s) are not in this database; they count "
            "as relevant jobs that were not retrieved."
        )
    if any(result.degraded for mode in report.modes for result in mode.results):
        notes.append(
            f"WARNING: '{DEGRADED_MARK}' marks queries whose embedding failed, so the vector part "
            "is missing from that result; the numbers for those queries are not comparable."
        )
    return notes


def format_report(report: "EvalReport", database: str) -> str:
    lines = [f"database: {database}   k={report.k}   candidates per list: {report.candidates}", ""]
    lines += _header(report)
    lines += _query_rows(report)
    lines.append(_mean_row(report))
    lines.append("")
    lines += _notes(report)
    return "\n".join(lines)


def _aggregate_dict(summary: Aggregate) -> dict[str, Any]:
    return {
        "queries_scored": summary.queries_scored,
        "queries_excluded": summary.queries_excluded,
        "mean_recall": summary.mean_recall,
        "mean_precision": summary.mean_precision,
        "mrr": summary.mean_reciprocal_rank,
        "mean_ndcg": summary.mean_ndcg,
    }


def _result_dict(result: "QueryResult") -> dict[str, Any]:
    metrics = result.metrics
    return {
        "query": result.query,
        "relevant": metrics.relevant_count,
        "retrieved": metrics.retrieved_count,
        "recall": metrics.recall,
        "precision": metrics.precision,
        "reciprocal_rank": metrics.reciprocal_rank,
        "ndcg": metrics.ndcg,
        "degraded": result.degraded,
        "missing_refs": list(result.missing_refs),
        "ranked": list(result.ranked),
    }


def _mode_dict(mode: "ModeReport") -> dict[str, Any]:
    return {
        "mode": mode.mode.value,
        "aggregate": _aggregate_dict(mode.summary),
        "queries": [_result_dict(result) for result in mode.results],
    }


def report_to_dict(report: "EvalReport", database: str) -> dict[str, Any]:
    return {
        "database": database,
        "k": report.k,
        "candidates": report.candidates,
        "modes": [_mode_dict(mode) for mode in report.modes],
    }
