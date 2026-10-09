import hashlib

SEPARATOR = "\x1e"


def make_hash(job) -> str:
    fields = [
        str(job.get("company", "")),
        str(job.get("position", "")),
        str(job.get("description", "")),
        str(job.get("location", "")),
    ]
    combined = SEPARATOR.join(fields)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
