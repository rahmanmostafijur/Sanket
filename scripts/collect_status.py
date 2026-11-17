"""Regenerate the mechanical parts of docs/STATUS.md.

    python scripts/collect_status.py                      # print the blocks
    python scripts/collect_status.py --write              # update docs/STATUS.md in place
    python scripts/collect_status.py --write --pytest-summary "1500 passed in 140s"

Only the text between `<!-- AUTO:name -->` and `<!-- /AUTO:name -->` markers is replaced; the
rest of the file is written by hand and is never touched. The blocks are:

  adr-list    one row per file in docs/adr; the Summary column is kept from the existing row
              (a new ADR gets a TODO-ORCH marker to fill in)
  migrations  the Alembic revision chain read from backend/alembic/versions, and its head(s)
  branch-logs the commits of each stacked branch (those that exist locally), each against the
              nearest earlier branch it is built on
  pytest      the pytest summary line given with --pytest-summary (left alone without it)

It uses only the standard library and read-only git commands (branch, log, merge-base).
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# The branches of the build, oldest first. A branch that does not exist is left out. After the
# feed and hardening branches are rebased onto each other, each lists only its own commits.
BRANCH_ORDER = (
    "feat/ci-tests",
    "feat/sources-more",
    "feat/m3-canonical",
    "feat/m4-index",
    "feat/m5-search",
    "feat/m6-matcher",
    "feat/m7-sse",
    "feat/m8-hardening",
    "feat/m9-integration",
)
BASE_BRANCH = "main"
TODO_MARKER = "<!-- TODO-ORCH: one-line summary -->"
SUMMARY_COLUMN = 3

IsAncestor = Callable[[str, str], bool]


# -- markers -------------------------------------------------------------------------------------


def marker_pair(name: str) -> tuple[str, str]:
    return f"<!-- AUTO:{name} -->", f"<!-- /AUTO:{name} -->"


def block_content(document: str, name: str) -> str | None:
    """The text currently between the markers of `name`, or None if the markers are missing."""
    start, end = marker_pair(name)
    begin = document.find(start)
    finish = document.find(end)
    if begin == -1 or finish == -1 or finish < begin:
        return None
    return document[begin + len(start) : finish].strip("\n")


def replace_block(document: str, name: str, content: str) -> str:
    """The document with the block `name` replaced by `content`. A missing block is an error."""
    start, end = marker_pair(name)
    begin = document.find(start)
    finish = document.find(end)
    if begin == -1 or finish == -1 or finish < begin:
        raise ValueError(f"STATUS.md has no {start} ... {end} block")
    return f"{document[: begin + len(start)]}\n{content.strip(chr(10))}\n{document[finish:]}"


# -- commits and branches ------------------------------------------------------------------------


@dataclass(frozen=True)
class Commit:
    short_hash: str
    subject: str


def parse_log(output: str) -> list[Commit]:
    """Commits from `git log --format=%h%x09%s`, newest first as git prints them."""
    commits = []
    for line in output.splitlines():
        short_hash, _, subject = line.partition("\t")
        if short_hash and subject:
            commits.append(Commit(short_hash.strip(), subject.strip()))
    return commits


def choose_parents(branches: Sequence[str], base: str, is_ancestor: IsAncestor) -> dict[str, str]:
    """For each branch, the nearest earlier branch it is built on, else `base`.

    `is_ancestor(a, b)` says whether `a` is contained in `b`.
    """
    parents: dict[str, str] = {}
    for position, branch in enumerate(branches):
        parent = base
        for earlier in reversed(branches[:position]):
            if is_ancestor(earlier, branch):
                parent = earlier
                break
        parents[branch] = parent
    return parents


def render_branch_log(branch: str, parent: str, commits: Sequence[Commit]) -> str:
    noun = "commit" if len(commits) == 1 else "commits"
    lines = [f"#### `{branch}` ({len(commits)} {noun} on `{parent}`)", ""]
    if not commits:
        return "\n".join([*lines, "(no commits of its own)", ""])
    lines.append("```")
    lines.extend(f"{commit.short_hash} {commit.subject}" for commit in commits)
    lines.extend(["```", ""])
    return "\n".join(lines)


def render_branch_logs(parents: Mapping[str, str], logs: Mapping[str, Sequence[Commit]]) -> str:
    return "\n".join(render_branch_log(b, parents[b], logs[b]) for b in parents).rstrip()


# -- ADRs ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Adr:
    number: str
    title: str
    status: str
    filename: str


ADR_NAME = re.compile(r"^(\d{4})-.+\.md$")
ADR_TITLE = re.compile(r"^#\s*(?:\d{4}\s*[:.-]\s*)?(.+)$", re.MULTILINE)
ADR_STATUS = re.compile(r"^Status:\s*(.+)$", re.MULTILINE)


def parse_adr(filename: str, text: str) -> Adr | None:
    """The ADR in `text`, or None when the file name is not `NNNN-title.md`."""
    named = ADR_NAME.match(filename)
    if named is None:
        return None
    title = ADR_TITLE.search(text)
    status = ADR_STATUS.search(text)
    return Adr(
        number=named.group(1),
        title=title.group(1).strip() if title else filename,
        status=status.group(1).strip() if status else "unknown",
        filename=filename,
    )


def existing_summaries(block: str | None) -> dict[str, str]:
    """Number to summary from the rows of an earlier adr-list block."""
    summaries: dict[str, str] = {}
    for line in (block or "").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) > SUMMARY_COLUMN and re.fullmatch(r"\d{4}", cells[0]):
            summaries[cells[0]] = cells[SUMMARY_COLUMN]
    return summaries


def render_adr_table(adrs: Sequence[Adr], summaries: Mapping[str, str]) -> str:
    lines = ["| ADR | Title | Status | Summary |", "| --- | --- | --- | --- |"]
    for adr in sorted(adrs, key=lambda a: a.number):
        summary = summaries.get(adr.number) or TODO_MARKER
        lines.append(f"| {adr.number} | {adr.title} | {adr.status} | {summary} |")
    return "\n".join(lines)


# -- migrations ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Revision:
    revision: str
    down_revision: str | None
    message: str


REVISION = re.compile(r"""^revision\b[^=\n]*=\s*["']([^"']+)["']""", re.MULTILINE)
DOWN_REVISION = re.compile(
    r"""^down_revision\b[^=\n]*=\s*(?:["']([^"']+)["']|None)""", re.MULTILINE
)


def parse_revision(text: str) -> Revision | None:
    """A revision from the source of an Alembic version file, or None if it has none."""
    revision = REVISION.search(text)
    down = DOWN_REVISION.search(text)
    if revision is None or down is None:
        return None
    first_line = text.lstrip().removeprefix('"""').strip().splitlines()[0:1]
    return Revision(revision.group(1), down.group(1), first_line[0].strip() if first_line else "")


def revision_heads(revisions: Sequence[Revision]) -> list[str]:
    """Revisions that no other revision builds on. Exactly one means a linear history."""
    parents = {r.down_revision for r in revisions}
    return sorted(r.revision for r in revisions if r.revision not in parents)


def order_chain(revisions: Sequence[Revision]) -> list[Revision]:
    """Oldest first, following down_revision from the root. Forks keep file-name order."""
    by_parent: dict[str | None, list[Revision]] = {}
    for revision in revisions:
        by_parent.setdefault(revision.down_revision, []).append(revision)
    ordered: list[Revision] = []
    pending = list(reversed(by_parent.get(None, [])))
    while pending:
        current = pending.pop()
        ordered.append(current)
        pending.extend(reversed(by_parent.get(current.revision, [])))
    return ordered


def render_migrations(revisions: Sequence[Revision]) -> str:
    heads = revision_heads(revisions)
    lines = ["| # | Revision | Message |", "| --- | --- | --- |"]
    for position, revision in enumerate(order_chain(revisions), start=1):
        lines.append(f"| {position} | `{revision.revision}` | {revision.message} |")
    linear = "yes" if len(heads) == 1 else "NO"
    head_text = ", ".join(f"`{head}`" for head in heads) or "none"
    return "\n".join([*lines, "", f"Head: {head_text}. Single linear head: {linear}."])


# -- pytest --------------------------------------------------------------------------------------


def render_pytest(summary: str) -> str:
    return f"Last gate run: `{summary.strip()}`"


# -- reading the repository ----------------------------------------------------------------------


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def local_branches(repo: Path) -> set[str]:
    result = git(repo, "branch", "--format=%(refname:short)")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def branch_log(repo: Path, parent: str, branch: str) -> list[Commit]:
    result = git(repo, "log", "--format=%h%x09%s", f"{parent}..{branch}")
    return parse_log(result.stdout)


def collect_branch_logs(repo: Path) -> str:
    existing = local_branches(repo)
    branches = [b for b in BRANCH_ORDER if b in existing]

    def is_ancestor(earlier: str, later: str) -> bool:
        return git(repo, "merge-base", "--is-ancestor", earlier, later).returncode == 0

    parents = choose_parents(branches, BASE_BRANCH, is_ancestor)
    logs = {branch: branch_log(repo, parents[branch], branch) for branch in branches}
    return render_branch_logs(parents, logs)


def collect_adrs(repo: Path, previous: str | None) -> str:
    adr_dir = repo / "docs" / "adr"
    adrs = []
    for path in sorted(adr_dir.glob("*.md")):
        adr = parse_adr(path.name, path.read_text(encoding="utf-8"))
        if adr is not None:
            adrs.append(adr)
    return render_adr_table(adrs, existing_summaries(previous))


def collect_migrations(repo: Path) -> str:
    revisions = []
    for path in sorted((repo / "backend" / "alembic" / "versions").glob("*.py")):
        revision = parse_revision(path.read_text(encoding="utf-8"))
        if revision is not None:
            revisions.append(revision)
    return render_migrations(revisions)


def collect_blocks(repo: Path, document: str, pytest_summary: str | None) -> dict[str, str]:
    """The regenerated blocks by name. The pytest block is only present when a summary is given."""
    blocks = {
        "adr-list": collect_adrs(repo, block_content(document, "adr-list")),
        "migrations": collect_migrations(repo),
        "branch-logs": collect_branch_logs(repo),
    }
    if pytest_summary:
        blocks["pytest"] = render_pytest(pytest_summary)
    return blocks


def update_document(document: str, blocks: Mapping[str, str]) -> str:
    updated = document
    for name, content in blocks.items():
        updated = replace_block(updated, name, content)
    return updated


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--status", type=Path, help="default: <repo>/docs/STATUS.md")
    parser.add_argument("--write", action="store_true", help="update STATUS.md in place")
    parser.add_argument("--pytest-summary", help='for example "1500 passed in 140s"')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    status_path = args.status or args.repo / "docs" / "STATUS.md"
    document = status_path.read_text(encoding="utf-8") if status_path.exists() else ""
    blocks = collect_blocks(args.repo, document, args.pytest_summary)
    if not args.write:
        for name, content in blocks.items():
            print(f"## {name}\n{content}\n")
        return 0
    try:
        updated = update_document(document, blocks)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    status_path.write_text(updated, encoding="utf-8", newline="\n")
    print(f"updated {', '.join(blocks)} in {status_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
