import hashlib

URL = "https://remoteok.com/api"
USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"
SEPARATOR = "\x1e"

def make_hash(job) -> str:
    fields = [
        job.get("company", ""),
        job.get("position", ""),
        job.get("description", ""),
        job.get("location", ""),
    ]
    combined = SEPARATOR.join(fields)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
