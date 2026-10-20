from sqlalchemy import Engine, Row, exists, select

from sanket.db import engine
from sanket.models import Posting, PostingExtraction


def find_pending(model: str, limit: int, db_engine: Engine = engine) -> list[Row]:
    already_done = exists().where(
        PostingExtraction.posting_id == Posting.id,
        PostingExtraction.content_hash == Posting.content_hash,
        PostingExtraction.model == model,
    )
    stmt = (
        select(Posting.id, Posting.raw, Posting.content_hash)
        .where(~already_done)
        .order_by(Posting.id)
        .limit(limit)
    )
    with db_engine.connect() as conn:
        return list(conn.execute(stmt))
