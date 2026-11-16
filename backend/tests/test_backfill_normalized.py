import pytest
from sqlalchemy import Engine, insert, select

from sanket.backfill_normalized import (
    CONVERTERS,
    BackfillSummary,
    backfill,
    parse_args,
)
from sanket.models import Posting
from sanket.sources import weworkremotely
from sanket.storage import NORMALIZED_FIELDS
from tests.source_helpers import load_bytes, load_json

LEGACY_HASH = "legacy-hash"


def raw_samples() -> list[tuple[str, str, dict, str]]:
    """(source, source_id, stored raw, expected title) for every adapter."""
    wwr_item = weworkremotely.parse_feed(load_bytes("weworkremotely.xml"))[0]
    return [
        ("greenhouse", "acme:4001", load_json("greenhouse.json")["jobs"][0], "Platform Engineer"),
        ("lever", "acme:aaaa-1111", load_json("lever.json")[0], "Staff Engineer"),
        (
            "himalayas",
            "https://himalayas.app/companies/acme/jobs/backend-engineer",
            load_json("himalayas.json")["first_page"]["jobs"][0],
            "Backend Engineer",
        ),
        (
            "jobicy",
            "101",
            load_json("jobicy.json")["first_page"]["jobs"][0],
            "Backend & API Developer",
        ),
        ("weworkremotely", wwr_item["guid"], wwr_item, "Senior Python Developer"),
        ("remoteok", "9001", load_json("remoteok.json")[1], "Backend Dev"),
        ("remotive", "2001", load_json("remotive.json")["jobs"][0], "Data Analyst"),
    ]


def add_legacy_row(engine: Engine, source: str, source_id: str, raw: dict, **fields) -> int:
    """A posting stored without its normalized fields, as before they existed."""
    stmt = (
        insert(Posting)
        .values(source=source, source_id=source_id, raw=raw, content_hash=LEGACY_HASH, **fields)
        .returning(Posting.id)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar_one()


def read_post(engine: Engine, posting_id: int):
    with engine.connect() as conn:
        return conn.execute(select(Posting).where(Posting.id == posting_id)).one()


def seed_all_sources(engine: Engine) -> dict[str, int]:
    return {
        source: add_legacy_row(engine, source, source_id, raw)
        for source, source_id, raw, _ in raw_samples()
    }


def test_dry_run_reports_changes_and_writes_nothing(clean_db) -> None:
    ids = seed_all_sources(clean_db)

    summary = backfill(clean_db, apply=False)

    assert summary == BackfillSummary(scanned=7, changed=7, applied=False)
    for posting_id in ids.values():
        row = read_post(clean_db, posting_id)
        assert row.title is None
        assert row.description is None


@pytest.mark.parametrize(("source", "source_id", "raw", "title"), raw_samples())
def test_apply_fills_the_fields_the_adapter_derives_from_raw(
    clean_db, source, source_id, raw, title
) -> None:
    posting_id = add_legacy_row(clean_db, source, source_id, raw)

    summary = backfill(clean_db, apply=True)

    row = read_post(clean_db, posting_id)
    expected = CONVERTERS[source](source_id, raw)
    assert summary == BackfillSummary(scanned=1, changed=1, applied=True)
    assert row.title == title
    for name in NORMALIZED_FIELDS:
        assert getattr(row, name) == getattr(expected, name), name


def test_apply_never_changes_the_content_hash_or_updated_at(clean_db) -> None:
    ids = seed_all_sources(clean_db)
    before = {source: read_post(clean_db, posting_id) for source, posting_id in ids.items()}

    backfill(clean_db, apply=True)

    for source, posting_id in ids.items():
        after = read_post(clean_db, posting_id)
        assert after.content_hash == LEGACY_HASH
        assert after.updated_at == before[source].updated_at
        assert after.raw == before[source].raw


def test_apply_corrects_fields_that_differ_from_raw(clean_db) -> None:
    source, source_id, raw, title = raw_samples()[0]
    posting_id = add_legacy_row(
        clean_db, source, source_id, raw, title="Stale Title", description="stale text"
    )

    summary = backfill(clean_db, apply=True)

    row = read_post(clean_db, posting_id)
    assert summary.changed == 1
    assert row.title == title
    assert row.description != "stale text"


def test_apply_is_idempotent(clean_db) -> None:
    seed_all_sources(clean_db)
    backfill(clean_db, apply=True)

    second = backfill(clean_db, apply=True)

    assert second == BackfillSummary(scanned=7, changed=0, applied=True)


def test_rows_that_already_match_are_left_alone(clean_db) -> None:
    source, source_id, raw, _ = raw_samples()[0]
    expected = CONVERTERS[source](source_id, raw)
    current = {name: getattr(expected, name) for name in NORMALIZED_FIELDS}
    posting_id = add_legacy_row(clean_db, source, source_id, raw, **current)
    before = read_post(clean_db, posting_id)

    summary = backfill(clean_db, apply=True)

    assert summary == BackfillSummary(scanned=1, changed=0, applied=True)
    assert read_post(clean_db, posting_id) == before


def test_unknown_sources_and_malformed_raw_are_counted_and_skipped(clean_db) -> None:
    good_source, good_id, good_raw, good_title = raw_samples()[0]
    unknown = add_legacy_row(clean_db, "mystery", "1", {"title": "x"})
    malformed = add_legacy_row(clean_db, "greenhouse", "acme:9", {"id": 9})
    good = add_legacy_row(clean_db, good_source, good_id, good_raw)

    summary = backfill(clean_db, apply=True)

    assert summary == BackfillSummary(
        scanned=3, changed=1, applied=True, unknown_source=1, failed=1
    )
    assert read_post(clean_db, good).title == good_title
    assert read_post(clean_db, unknown).title is None
    assert read_post(clean_db, malformed).title is None


def test_rows_are_processed_in_batches(clean_db) -> None:
    _, _, raw, _ = raw_samples()[0]
    for number in range(5):
        add_legacy_row(clean_db, "greenhouse", f"acme:{number}", dict(raw, id=number))

    summary = backfill(clean_db, apply=True, batch_size=2)

    assert summary == BackfillSummary(scanned=5, changed=5, applied=True)
    with clean_db.connect() as conn:
        titles = list(conn.scalars(select(Posting.title)))
    assert titles == ["Platform Engineer"] * 5


def test_dry_run_is_the_default() -> None:
    assert parse_args([]).apply is False
    assert parse_args(["--dry-run"]).apply is False
    assert parse_args(["--apply"]).apply is True


def test_dry_run_and_apply_cannot_be_combined() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--apply"])


def test_batch_size_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "0"])
