import logging

from sanket.sources.remoteok import fetch_remoteok_jobs
from sanket.storage import save_postings, to_row

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    jobs = fetch_remoteok_jobs()
    logger.info("Fetched %d jobs", len(jobs))
    rows = [to_row(job) for job in jobs]
    save_postings(rows)
    logger.info("Saved %d postings", len(rows))


if __name__ == "__main__":
    main()
