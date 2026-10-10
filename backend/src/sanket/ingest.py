from sanket.sources.remoteok import fetch_remoteok_jobs
from sanket.storage import save_postings, to_row


def main() -> None:
    jobs = fetch_remoteok_jobs()
    rows = [to_row(job) for job in jobs]
    save_postings(rows)
    print(f"Saved {len(rows)} postings to the database.")


if __name__ == "__main__":
    main()
