from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert

from sanket.db import engine
from sanket.hashing import make_hash
from sanket.models import Posting

SOURCE = "remoteok"


def to_row(job: dict) -> dict:
    return {
        "source": SOURCE,
        "source_id": str(job["id"]),
        "raw": job,
        "content_hash": make_hash(job),
    }


def save_postings(rows: list[dict]) -> None:
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
    with engine.begin() as conn:
        conn.execute(stmt)
