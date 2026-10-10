import httpx

URL = "https://remoteok.com/api"
USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"


def fetch_remoteok_jobs():
    response = httpx.get(
        URL,
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(10.0, connect=5.0),
    )
    response.raise_for_status()
    data = response.json()

    jobs = [item for item in data if "id" in item]
    return jobs
