from sqlalchemy import Engine, case, func
from sqlalchemy.dialects.postgresql import insert

from sanket.db import engine
from sanket.hashing import content_hash
from sanket.models import Posting
from sanket.sources.base import NormalizedPosting


def to_row(posting: NormalizedPosting) -> dict:
    return {
        "source": posting.source,
        "source_id": posting.source_id,
        "raw": posting.raw,
        "content_hash": content_hash(posting),
    }


def save_postings(rows: list[dict], db_engine: Engine = engine) -> None:
    stmt = insert(Posting).values(rows)
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
    with db_engine.begin() as conn:
        conn.execute(stmt)
