from sanket.hashing import content_hash
from sanket.sources.base import NormalizedPosting
from sanket.storage import to_row


def test_to_row_maps_job_fields() -> None:
    posting = NormalizedPosting(
        source="remoteok",
        source_id="123",
        url="https://example.com/jobs/123",
        title="engineer",
        raw={"id": 123},
    )

    row = to_row(posting)

    assert row["source"] == "remoteok"
    assert row["source_id"] == "123"
    assert row["raw"] == {"id": 123}
    assert row["content_hash"] == content_hash(posting)
