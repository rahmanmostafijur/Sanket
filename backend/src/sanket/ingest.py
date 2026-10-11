import logging

from sanket.sources.remoteok import fetch_remoteok_jobs
from sanket.sources.remotive import fetch_remotive_jobs
from sanket.storage import save_postings, to_row

logger = logging.getLogger(__name__)

SOURCES = {
    "remoteok": fetch_remoteok_jobs,
    "remotive": fetch_remotive_jobs,
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    failed = []
    for name, fetch in SOURCES.items():
        try:
            jobs = fetch()
            logger.info("Fetched %d jobs from %s", len(jobs), name)
            rows = [to_row(job, name) for job in jobs]
            save_postings(rows)
            logger.info("Saved %d postings from %s", len(rows), name)
        except Exception:
            logger.exception("Source %s failed", name)
            failed.append(name)

    if failed:
        raise SystemExit(f"Failed sources: {', '.join(failed)}")


if __name__ == "__main__":
    main()
