import pytest

from sanket.config import settings
from sanket.indexing import __main__ as cli
from sanket.indexing.service import IndexSummary


def test_default_is_a_dry_run() -> None:
    args = cli.parse_args([])

    assert (args.apply, args.dry_run, args.limit, args.batch_size) == (False, False, None, None)


def test_apply_limit_and_batch_size_are_parsed() -> None:
    args = cli.parse_args(["--apply", "--limit", "5", "--batch-size", "7"])

    assert (args.apply, args.limit, args.batch_size) == (True, 5, 7)


def test_apply_and_dry_run_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--apply", "--dry-run"])


def test_limit_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--limit", "0"])


def test_dry_run_needs_no_api_key_and_passes_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_index(cfg, client, *, limit, apply):
        seen.update(client=client, limit=limit, apply=apply)
        return IndexSummary()

    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_pending", fake_index)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    cli.main([])

    assert seen == {"client": None, "limit": None, "apply": False}


def test_apply_without_an_api_key_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        cli.main(["--apply"])


def test_failed_jobs_make_the_command_exit_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "check_dimensions", lambda dimensions, db_engine: None)
    monkeypatch.setattr(cli, "index_pending", lambda *a, **k: IndexSummary(failed=2))

    with pytest.raises(SystemExit, match="2 jobs failed"):
        cli.main([])


def test_summary_line_lists_every_counter() -> None:
    line = IndexSummary(scanned=3, embedded=2, applied=True).line("m")

    for key in (
        "mode=apply",
        "model=m",
        "scanned=3",
        "tsvector_updated=0",
        "embedded=2",
        "unchanged=0",
        "removed=0",
        "skipped_no_text=0",
        "failed=0",
    ):
        assert key in line
