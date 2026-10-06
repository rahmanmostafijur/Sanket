import hashlib
import httpx

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

response = httpx.get(
    URL,
    headers={"User-Agent": USER_AGENT},
    timeout=httpx.Timeout(10.0, connect=5.0),
)
response.raise_for_status()
data = response.json()

print(f"Total items: {len(data)}")

print(make_hash(data[1]))  # Print the hash of the second job posting
print(make_hash(data[2]))  # Print the hash of the third job posting
print(make_hash(data[3]))  # Print the hash of the fourth job posting