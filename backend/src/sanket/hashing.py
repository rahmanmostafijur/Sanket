import hashlib

from sanket.sources.base import NormalizedPosting

SEPARATOR = "\x1e"
HASH_VERSION = "v1"


def make_hash(job) -> str:
    fields = [
        str(job.get("company", "")),
        str(job.get("position", "")),
        str(job.get("description", "")),
        str(job.get("location", "")),
    ]
    combined = SEPARATOR.join(fields)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def content_hash(posting: NormalizedPosting) -> str:
    fields = [
        posting.title,
        posting.company or "",
        posting.location or "",
        posting.description or "",
        posting.salary_text or "",
        posting.deadline.isoformat() if posting.deadline else "",
    ]
    combined = SEPARATOR.join(fields)
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return f"{HASH_VERSION}:{digest}"
