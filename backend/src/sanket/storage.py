from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, case, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from sanket.db import engine
from sanket.hashing import content_hash
from sanket.models import Posting
from sanket.sources.base import NormalizedPosting

# Keeps each INSERT well below PostgreSQL's 65535 bind-parameter limit.
CHUNK_SIZE = 1000

PostingKey = tuple[str, str]


@dataclass(frozen=True)
class SaveResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0


def to_row(posting: NormalizedPosting) -> dict:
    return {
        "source": posting.source,
        "source_id": posting.source_id,
        "raw": posting.raw,
        "content_hash": content_hash(posting),
        "url": posting.url,
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "description": posting.description,
        "salary_text": posting.salary_text,
        "published_at": posting.published_at,
        "deadline": posting.deadline,
    }


def dedupe_rows(rows: Sequence[dict]) -> list[dict]:
    """Keep the last row per (source, source_id); one upsert cannot touch a row twice."""
    by_key = {(row["source"], row["source_id"]): row for row in rows}
    return list(by_key.values())


def classify(rows: Sequence[dict], existing: dict[PostingKey, str]) -> SaveResult:
    new = updated = unchanged = 0
    for row in rows:
        previous = existing.get((row["source"], row["source_id"]))
        if previous is None:
            new += 1
        elif previous != row["content_hash"]:
            updated += 1
        else:
            unchanged += 1
    return SaveResult(new=new, updated=updated, unchanged=unchanged)


def _chunks(rows: Sequence[dict], size: int = CHUNK_SIZE) -> Iterator[Sequence[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _existing_hashes(conn: Connection, rows: Sequence[dict]) -> dict[PostingKey, str]:
    keys = [(row["source"], row["source_id"]) for row in rows]
    stmt = select(Posting.source, Posting.source_id, Posting.content_hash).where(
        tuple_(Posting.source, Posting.source_id).in_(keys)
    )
    return {(source, source_id): digest for source, source_id, digest in conn.execute(stmt)}


def _upsert(conn: Connection, rows: Sequence[dict]) -> None:
    stmt = insert(Posting).values(list(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=[Posting.source, Posting.source_id],
        set_={
            "raw": stmt.excluded.raw,
            "content_hash": stmt.excluded.content_hash,
            "last_seen_at": func.now(),
            "updated_at": case(
                (Posting.content_hash != stmt.excluded.content_hash, func.now()),
                else_=Posting.updated_at,
            ),
        },
    )
    conn.execute(stmt)


def save_postings(rows: list[dict], db_engine: Engine = engine) -> SaveResult:
    """Upsert postings on (source, source_id) and report how many were new or changed."""
    rows = dedupe_rows(rows)
    if not rows:
        return SaveResult()
    existing: dict[PostingKey, str] = {}
    with db_engine.begin() as conn:
        for chunk in _chunks(rows):
            existing.update(_existing_hashes(conn, chunk))
            _upsert(conn, chunk)
    return classify(rows, existing)
