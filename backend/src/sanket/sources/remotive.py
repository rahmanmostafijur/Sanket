import httpx

URL = "https://remotive.com/api/remote-jobs"
USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"


def fetch_remotive_jobs() -> list[dict]:
    response = httpx.get(
        URL,
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(10.0, connect=5.0),
    )
    response.raise_for_status()
    data = response.json()

    return [
        {
            **job,
            "company": job["company_name"],
            "position": job["title"],
            "location": job["candidate_required_location"],
        }
        for job in data["jobs"]
    ]
