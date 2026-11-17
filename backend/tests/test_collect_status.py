"""scripts/collect_status.py: the pure parts, and one run against a throwaway git repository."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collect_status.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_status", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["collect_status"] = module
    spec.loader.exec_module(module)
    return module


cs = load_script()


# -- markers -------------------------------------------------------------------------------------


def document(name: str = "x", body: str = "old") -> str:
    start, end = cs.marker_pair(name)
    return f"intro\n{start}\n{body}\n{end}\noutro\n"


def test_block_content_returns_the_text_between_the_markers() -> None:
    assert cs.block_content(document(body="a\nb"), "x") == "a\nb"


def test_block_content_is_none_when_markers_are_missing_or_reversed() -> None:
    start, end = cs.marker_pair("x")

    assert cs.block_content("nothing here", "x") is None
    assert cs.block_content(f"{end}\n{start}", "x") is None


def test_replace_block_changes_only_what_is_between_the_markers() -> None:
    result = cs.replace_block(document(body="old"), "x", "new\nlines")

    assert result == document(body="new\nlines")
    assert result.startswith("intro\n") and result.endswith("outro\n")


def test_replace_block_is_idempotent() -> None:
    once = cs.replace_block(document(), "x", "same")

    assert cs.replace_block(once, "x", "same") == once


def test_replace_block_rejects_a_missing_block() -> None:
    with pytest.raises(ValueError, match="AUTO:x"):
        cs.replace_block("no markers", "x", "content")


def test_update_document_replaces_each_named_block() -> None:
    both = document("a") + document("b")

    result = cs.update_document(both, {"a": "1", "b": "2"})

    assert cs.block_content(result, "a") == "1"
    assert cs.block_content(result, "b") == "2"


# -- commits and branches ------------------------------------------------------------------------


def test_parse_log_reads_hash_and_subject_and_skips_blank_lines() -> None:
    output = "abc1234\tfeat(x): add y\n\ndef5678\tfix: a\ttab in subject\n"

    assert cs.parse_log(output) == [
        cs.Commit("abc1234", "feat(x): add y"),
        cs.Commit("def5678", "fix: a\ttab in subject"),
    ]


def test_each_branch_is_compared_with_the_nearest_earlier_branch_it_contains() -> None:
    stacked = {("a", "b"), ("a", "c"), ("b", "c")}

    parents = cs.choose_parents(["a", "b", "c"], "main", lambda x, y: (x, y) in stacked)

    assert parents == {"a": "main", "b": "a", "c": "b"}


def test_sibling_branches_are_both_compared_with_their_shared_parent() -> None:
    # m7 and m8 are built on m6 and not on each other, until they are rebased.
    contained = {("m6", "m7"), ("m6", "m8")}

    parents = cs.choose_parents(["m6", "m7", "m8"], "main", lambda x, y: (x, y) in contained)

    assert parents == {"m6": "main", "m7": "m6", "m8": "m6"}


def test_after_a_rebase_the_later_branch_is_compared_with_the_earlier_one() -> None:
    contained = {("m6", "m7"), ("m6", "m8"), ("m7", "m8")}

    parents = cs.choose_parents(["m6", "m7", "m8"], "main", lambda x, y: (x, y) in contained)

    assert parents["m8"] == "m7"


def test_render_branch_log_lists_the_commits_with_a_count() -> None:
    text = cs.render_branch_log("feat/x", "main", [cs.Commit("a1", "feat: one")])

    assert text.splitlines()[0] == "#### `feat/x` (1 commit on `main`)"
    assert "a1 feat: one" in text


def test_render_branch_log_handles_plural_and_empty() -> None:
    two = cs.render_branch_log("b", "a", [cs.Commit("1", "x"), cs.Commit("2", "y")])
    none = cs.render_branch_log("b", "a", [])

    assert "(2 commits on `a`)" in two
    assert "(no commits of its own)" in none


# -- ADRs ----------------------------------------------------------------------------------------


def test_parse_adr_reads_number_title_and_status() -> None:
    adr = cs.parse_adr("0003-job-indexing.md", "# 0003: Indexing jobs\n\nStatus: accepted\n")

    assert adr == cs.Adr("0003", "Indexing jobs", "accepted", "0003-job-indexing.md")


def test_parse_adr_tolerates_a_plain_title_and_a_missing_status() -> None:
    adr = cs.parse_adr("0010-x.md", "# Use a thing\n")

    assert adr is not None
    assert (adr.title, adr.status) == ("Use a thing", "unknown")


@pytest.mark.parametrize("name", ["README.md", "template.md", "12-short.md", "0001-x.txt"])
def test_parse_adr_ignores_files_that_are_not_adrs(name: str) -> None:
    assert cs.parse_adr(name, "# x\n") is None


def test_the_adr_table_keeps_known_summaries_and_marks_new_adrs_for_filling_in() -> None:
    previous = (
        "| ADR | Title | Status | Summary |\n| --- | --- | --- | --- |\n"
        "| 0001 | Old title | accepted | The kept summary |\n"
    )
    adrs = [
        cs.Adr("0002", "Second", "accepted", "0002-second.md"),
        cs.Adr("0001", "First", "accepted", "0001-first.md"),
    ]

    table = cs.render_adr_table(adrs, cs.existing_summaries(previous))

    rows = table.splitlines()[2:]
    assert rows[0] == "| 0001 | First | accepted | The kept summary |"
    assert rows[1] == f"| 0002 | Second | accepted | {cs.TODO_MARKER} |"


def test_existing_summaries_ignore_the_header_and_other_text() -> None:
    block = "| ADR | Title | Status | Summary |\n| --- | --- | --- | --- |\ntext\n"

    assert cs.existing_summaries(block) == {}
    assert cs.existing_summaries(None) == {}


# -- migrations ----------------------------------------------------------------------------------

ROOT_FILE = '''"""create posting table

Revision ID: aaa111
Revises:
"""
revision: str = "aaa111"
down_revision: str | Sequence[str] | None = None
'''
CHILD_FILE = '''"""add job table

Revision ID: bbb222
"""
revision = 'bbb222'
down_revision = "aaa111"
'''


def test_parse_revision_reads_both_styles_of_assignment_and_the_message() -> None:
    assert cs.parse_revision(ROOT_FILE) == cs.Revision("aaa111", None, "create posting table")
    assert cs.parse_revision(CHILD_FILE) == cs.Revision("bbb222", "aaa111", "add job table")


def test_parse_revision_is_none_for_a_file_that_is_not_a_revision() -> None:
    assert cs.parse_revision("print('hello')") is None


def test_a_linear_history_has_one_head_and_is_listed_oldest_first() -> None:
    revisions = [
        cs.Revision("c", "b", "third"),
        cs.Revision("a", None, "first"),
        cs.Revision("b", "a", "second"),
    ]

    assert cs.revision_heads(revisions) == ["c"]
    assert [r.revision for r in cs.order_chain(revisions)] == ["a", "b", "c"]
    text = cs.render_migrations(revisions)
    assert "| 1 | `a` | first |" in text
    assert text.endswith("Head: `c`. Single linear head: yes.")


def test_two_heads_are_reported_as_not_linear() -> None:
    revisions = [
        cs.Revision("a", None, "first"),
        cs.Revision("b", "a", "left"),
        cs.Revision("c", "a", "right"),
    ]

    assert cs.revision_heads(revisions) == ["b", "c"]
    assert "Single linear head: NO" in cs.render_migrations(revisions)


def test_render_pytest_names_the_summary() -> None:
    assert cs.render_pytest(" 12 passed in 1s \n") == "Last gate run: `12 passed in 1s`"


# -- a throwaway repository ----------------------------------------------------------------------

STATUS_TEMPLATE = """# Status

{adr}

{migrations}

{logs}

{pytest}
"""


def run_git(repo: Path, *args: str) -> None:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "-C", str(repo), *identity, *args], check=True, capture_output=True)


def commit(repo: Path, name: str, message: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    run_git(repo, "add", name)
    run_git(repo, "commit", "-m", message)


def blocks_template() -> str:
    def wrap(name: str) -> str:
        start, end = cs.marker_pair(name)
        return f"{start}\n{end}"

    return STATUS_TEMPLATE.format(
        adr=wrap("adr-list"),
        migrations=wrap("migrations"),
        logs=wrap("branch-logs"),
        pytest=wrap("pytest"),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "backend" / "alembic" / "versions").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001-first.md").write_text("# 0001: First\n\nStatus: accepted\n")
    (tmp_path / "backend" / "alembic" / "versions" / "a_first.py").write_text(ROOT_FILE)
    (tmp_path / "docs" / "STATUS.md").write_text(blocks_template(), encoding="utf-8")
    commit(tmp_path, "base.txt", "chore: base")
    run_git(tmp_path, "checkout", "-q", "-b", "feat/ci-tests")
    commit(tmp_path, "one.txt", "feat: one")
    run_git(tmp_path, "checkout", "-q", "-b", "feat/sources-more")
    commit(tmp_path, "two.txt", "feat: two")
    commit(tmp_path, "three.txt", "fix: three")
    return tmp_path


def test_main_prints_the_blocks_without_changing_the_file(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (repo / "docs" / "STATUS.md").read_text(encoding="utf-8")

    assert cs.main(["--repo", str(repo)]) == 0

    out = capsys.readouterr().out
    assert "#### `feat/sources-more` (2 commits on `feat/ci-tests`)" in out
    assert "#### `feat/ci-tests` (1 commit on `main`)" in out
    assert "| 0001 | First | accepted |" in out
    assert "Single linear head: yes" in out
    assert (repo / "docs" / "STATUS.md").read_text(encoding="utf-8") == before


def test_main_write_fills_the_blocks_and_a_second_run_changes_nothing(repo: Path) -> None:
    status = repo / "docs" / "STATUS.md"
    args = ["--repo", str(repo), "--write", "--pytest-summary", "3 passed in 1s"]

    assert cs.main(args) == 0
    first = status.read_text(encoding="utf-8")
    assert cs.main(args) == 0

    assert status.read_text(encoding="utf-8") == first
    assert "fix: three" in first
    assert "Last gate run: `3 passed in 1s`" in first
    assert cs.TODO_MARKER in first
    assert first.startswith("# Status\n")


def test_main_write_keeps_hand_written_summaries(repo: Path) -> None:
    status = repo / "docs" / "STATUS.md"
    cs.main(["--repo", str(repo), "--write"])
    edited = status.read_text(encoding="utf-8").replace(cs.TODO_MARKER, "My summary")
    status.write_text(edited, encoding="utf-8")

    cs.main(["--repo", str(repo), "--write"])

    assert "| 0001 | First | accepted | My summary |" in status.read_text(encoding="utf-8")


def test_without_a_pytest_summary_that_block_is_left_alone(repo: Path) -> None:
    status = repo / "docs" / "STATUS.md"
    cs.main(["--repo", str(repo), "--write", "--pytest-summary", "9 passed"])

    cs.main(["--repo", str(repo), "--write"])

    assert "Last gate run: `9 passed`" in status.read_text(encoding="utf-8")


def test_main_write_reports_a_status_file_without_markers(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "docs" / "STATUS.md").write_text("# no markers\n", encoding="utf-8")

    assert cs.main(["--repo", str(repo), "--write"]) == 1

    assert "AUTO:adr-list" in capsys.readouterr().err
