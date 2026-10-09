from sanket.hashing import make_hash

SOURCE = "remoteok"


def to_row(job: dict) -> dict:
    return {
        "source": SOURCE,
        "source_id": str(job["id"]),
        "raw": job,
        "content_hash": make_hash(job),
    }
