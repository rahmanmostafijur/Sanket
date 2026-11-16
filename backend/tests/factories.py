"""Helpers that seed and read the test database for runner tests."""

from itertools import count

from sqlalchemy import Engine, Row, insert, null, select, update

from sanket.extraction.prompt import PROMPT_VERSION
from sanket.extraction.runner import STATUS_OK, ExtractionConfig
from sanket.extraction.schema import SCHEMA_VERSION
from sanket.models import Posting, PostingExtraction
from tests.test_extraction_schema import valid_data

CFG = ExtractionConfig(model="test-model", max_description_chars=2000, max_attempts=3)

_source_ids = count(1)


def add_posting(
    engine: Engine,
    *,
    source: str = "greenhouse",
    content_hash: str = "h1",
    title: str | None = "Backend Engineer",
    company: str | None = "Acme",
    location: str | None = "Remote",
    salary_text: str | None = None,
    description: str | None = "<p>Build APIs.</p>",
) -> int:
    stmt = (
        insert(Posting)
        .values(
            source=source,
            source_id=f"id-{next(_source_ids)}",
            raw={},
            content_hash=content_hash,
            title=title,
            company=company,
            location=location,
            salary_text=salary_text,
            description=description,
        )
        .returning(Posting.id)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar_one()


def set_content_hash(engine: Engine, posting_id: int, content_hash: str) -> None:
    stmt = update(Posting).where(Posting.id == posting_id).values(content_hash=content_hash)
    with engine.begin() as conn:
        conn.execute(stmt)


def add_extraction(
    engine: Engine,
    posting_id: int,
    *,
    status: str = STATUS_OK,
    content_hash: str = "h1",
    schema_version: int = SCHEMA_VERSION,
    prompt_version: int = PROMPT_VERSION,
    attempts: int = 1,
) -> None:
    is_ok = status == STATUS_OK
    stmt = insert(PostingExtraction).values(
        posting_id=posting_id,
        schema_version=schema_version,
        prompt_version=prompt_version,
        content_hash=content_hash,
        model="test-model",
        status=status,
        data=valid_data() if is_ok else null(),
        last_error=None if is_ok else "earlier failure",
        attempts=attempts,
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def get_extraction(
    engine: Engine,
    posting_id: int,
    schema_version: int = SCHEMA_VERSION,
    prompt_version: int = PROMPT_VERSION,
) -> Row | None:
    stmt = select(
        PostingExtraction.status,
        PostingExtraction.content_hash,
        PostingExtraction.model,
        PostingExtraction.attempts,
        PostingExtraction.last_error,
        PostingExtraction.input_tokens,
        PostingExtraction.output_tokens,
        PostingExtraction.data,
        PostingExtraction.data.is_(None).label("data_is_sql_null"),
    ).where(
        PostingExtraction.posting_id == posting_id,
        PostingExtraction.schema_version == schema_version,
        PostingExtraction.prompt_version == prompt_version,
    )
    with engine.connect() as conn:
        return conn.execute(stmt).one_or_none()


def count_extractions(engine: Engine) -> int:
    with engine.connect() as conn:
        return len(conn.execute(select(PostingExtraction.id)).all())
