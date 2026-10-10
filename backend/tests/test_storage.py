from sanket.hashing import make_hash
from sanket.storage import to_row


def test_to_row_maps_job_fields() -> None:
    job = {
        "id": 123,
        "company": "Acme",
        "position": "Backend Engineer",
        "description": "Build APIs",
        "location": "Remote",
    }
    row = to_row(job)
    assert row["source_id"] == "123"
    assert row["raw"] == job
    assert row["content_hash"] == make_hash(job)
