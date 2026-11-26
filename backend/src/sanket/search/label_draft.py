"""Draft a sheet of query and job pairs to label by hand: `python -m sanket.search.label_draft`.

For each query the sheet lists a few jobs that match its words in the full-text index and one or
more jobs picked at random, all from the database in DATABASE_URL, so the labeller sees good
matches and clear misses. The jobs of a query are shuffled and nothing says how a job was picked,
so the order and the file give no hint. The `grade` and `notes` columns are left blank.

Fill `grade` with 0 (not relevant), 1 (somewhat relevant), 2 (relevant) or 3 (highly relevant);
see docs/search-evaluation.md. `job_ref` is the job fingerprint that the labelled-query file
uses. The script labels nothing, tunes nothing and refuses to overwrite an existing sheet unless
`--force` is given, so hand labels are never lost by accident.
"""

import argparse
import csv
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from sanket.db import engine
from sanket.indexing.queries import fulltext_candidates
from sanket.models import Job, Posting

DEFAULT_OUT = Path("eval/label-draft.csv")
DEFAULT_HITS = 3
DEFAULT_PER_QUERY = 4
DEFAULT_SEED = 7
COLUMNS = (
    "query",
    "job_ref",
    "job_id",
    "title",
    "company",
    "location",
    "source",
    "url",
    "grade",
    "notes",
)

# Varied on purpose: bare roles, skills, seniority, remote and location wording, sentences and
# a vague one, so the sheet covers the ways people search.
DEFAULT_QUERIES: tuple[str, ...] = (
    "python backend engineer",
    "senior java developer",
    "react frontend developer",
    "remote data scientist",
    "devops engineer kubernetes aws",
    "machine learning engineer",
    "product manager",
    "ux designer",
    "junior software developer",
    "mobile developer android kotlin",
    "full stack typescript node",
    "qa automation engineer",
    "data analyst sql",
    "cybersecurity analyst",
    "technical writer",
    "customer support specialist",
    "marketing manager",
    "sales development representative",
    "site reliability engineer",
    "golang microservices",
    "remote part-time contract developer",
    "software engineer dhaka bangladesh",
    "entry level graduate software jobs in europe",
    "backend role at a fintech startup using postgres",
    "someone to build and scale our data pipelines",
)


def load_queries(path: Path) -> list[str]:
    """One query per line; blank lines and repeats are skipped."""
    seen: dict[str, None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            seen.setdefault(text, None)
    return list(seen)


def live_job_ids(db_engine: Engine) -> list[int]:
    """Jobs that still have a posting, in id order."""
    statement = select(Job.id).where(Job.posting_count > 0).order_by(Job.id)
    with db_engine.connect() as conn:
        return list(conn.execute(statement).scalars())


def pick_job_ids(
    db_engine: Engine,
    query: str,
    pool: Sequence[int],
    hits: int,
    per_query: int,
    rng: random.Random,
) -> list[int]:
    """Up to `hits` text matches, topped up with random non-matches to `per_query` jobs (at least
    one random job), all shuffled together."""
    matched = [c.job_id for c in fulltext_candidates(query, hits, db_engine)]
    taken = set(matched)
    others = [job_id for job_id in pool if job_id not in taken]
    extra = max(per_query - len(matched), 1)
    chosen = matched + rng.sample(others, min(extra, len(others)))
    rng.shuffle(chosen)
    return chosen


def job_details(db_engine: Engine, job_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    statement = (
        select(
            Job.id,
            Job.fingerprint,
            Job.title,
            Job.company,
            Job.location,
            Posting.source,
            Posting.url,
        )
        .outerjoin(Posting, Posting.id == Job.representative_posting_id)
        .where(Job.id.in_(job_ids))
    )
    with db_engine.connect() as conn:
        rows = conn.execute(statement).all()
    return {
        row.id: {
            "job_ref": row.fingerprint,
            "job_id": row.id,
            "title": row.title,
            "company": row.company,
            "location": row.location or "",
            "source": row.source or "",
            "url": row.url or "",
        }
        for row in rows
    }


def build_rows(
    db_engine: Engine,
    queries: Sequence[str],
    *,
    hits: int = DEFAULT_HITS,
    per_query: int = DEFAULT_PER_QUERY,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """One row per query and job pair, `grade` and `notes` blank. Same inputs, same rows."""
    rng = random.Random(seed)
    pool = live_job_ids(db_engine)
    rows: list[dict[str, Any]] = []
    for query in queries:
        ids = pick_job_ids(db_engine, query, pool, hits, per_query, rng)
        details = job_details(db_engine, ids)
        for job_id in ids:
            rows.append({"query": query, **details[job_id], "grade": "", "notes": ""})
    return rows


def write_sheet(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None, db_engine: Engine = engine) -> int:
    parser = argparse.ArgumentParser(description="Draft a query and job sheet to label by hand.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="CSV to write")
    parser.add_argument("--queries", type=Path, help="text file with one query per line")
    parser.add_argument("--hits", type=int, default=DEFAULT_HITS, help="text matches per query")
    parser.add_argument(
        "--per-query",
        type=int,
        default=DEFAULT_PER_QUERY,
        help="jobs per query, topped up at random",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    args = parser.parse_args(argv)
    if args.hits < 0 or args.per_query < 0:
        parser.error("--hits and --per-query must not be negative")
    if args.out.exists() and not args.force:
        print(
            f"{args.out} exists and may hold hand labels. Use --force to replace it.",
            file=sys.stderr,
        )
        return 1
    queries = load_queries(args.queries) if args.queries else list(DEFAULT_QUERIES)
    rows = build_rows(db_engine, queries, hits=args.hits, per_query=args.per_query, seed=args.seed)
    write_sheet(args.out, rows)
    print(f"{len(rows)} pairs for {len(queries)} queries written to {args.out}")
    print("Fill the grade column: 0 not relevant, 1 somewhat, 2 relevant, 3 highly relevant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
