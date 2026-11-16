import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from sanket.config import Settings, settings
from sanket.sources.ashby import AshbySource
from sanket.sources.base import Source, SourceNotConfiguredError
from sanket.sources.budget import DbRequestBudget, utc_now
from sanket.sources.greenhouse import GreenhouseSource
from sanket.sources.himalayas import HimalayasSource
from sanket.sources.http import BudgetExceededError, Fetcher, new_client
from sanket.sources.jobicy import JobicySource
from sanket.sources.jobtech_se import JobTechSource
from sanket.sources.lever import LeverSource
from sanket.sources.remoteok import RemoteOkSource
from sanket.sources.remotive import RemotiveSource
from sanket.sources.usajobs import UsaJobsSource
from sanket.sources.weworkremotely import WeWorkRemotelySource
from sanket.storage import SaveResult, save_postings, to_row

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class SourceSummary:
    name: str
    status: str
    fetched: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0

    def line(self) -> str:
        return (
            f"summary source={self.name} status={self.status} fetched={self.fetched} "
            f"new={self.new} updated={self.updated} unchanged={self.unchanged} "
            f"skipped={self.skipped} failed={self.failed}"
        )


def build_sources(config: Settings) -> list[Source]:
    return [
        RemoteOkSource(),
        RemotiveSource(),
        WeWorkRemotelySource(),
        JobicySource(),
        HimalayasSource(config.himalayas_api_key),
        GreenhouseSource(config.greenhouse_boards),
        LeverSource(config.lever_companies),
        AshbySource(config.ashby_boards),
        UsaJobsSource(config.usajobs_api_key, config.usajobs_user_agent_email),
        JobTechSource(
            config.jobtech_query,
            config.jobtech_max_pages,
            timedelta(days=config.jobtech_lookback_days),
        ),
    ]


def select_sources(sources: Sequence[Source], enabled: Sequence[str]) -> list[Source]:
    """Keep the sources named in `enabled`; an empty list keeps all of them."""
    if not enabled:
        return list(sources)
    known = {source.name for source in sources}
    unknown = sorted(set(enabled) - known)
    if unknown:
        raise SystemExit(f"Unknown INGEST_SOURCES: {', '.join(unknown)}")
    return [source for source in sources if source.name in enabled]


def too_soon(source: Source, last_run: datetime | None, now: datetime) -> bool:
    return (
        source.min_interval is not None
        and last_run is not None
        and now - last_run < source.min_interval
    )


def run_source(
    source: Source,
    http: Fetcher,
    last_run: datetime | None,
    now: datetime,
    save: Callable[[list[dict]], SaveResult] = save_postings,
) -> SourceSummary:
    if too_soon(source, last_run, now):
        logger.info(
            "%s: last run %s is within %s, skipping", source.name, last_run, source.min_interval
        )
        return SourceSummary(source.name, STATUS_SKIPPED, skipped=1)
    try:
        result = source.fetch(http)
        saved = save([to_row(posting) for posting in result.postings])
    except SourceNotConfiguredError as error:
        logger.info("%s: %s, skipping", source.name, error)
        return SourceSummary(source.name, STATUS_SKIPPED, skipped=1)
    except BudgetExceededError as error:
        logger.warning("%s: %s, skipping", source.name, error)
        return SourceSummary(source.name, STATUS_SKIPPED, skipped=1)
    except Exception:
        logger.exception("Source %s failed", source.name)
        return SourceSummary(source.name, STATUS_FAILED, failed=1)
    return SourceSummary(
        source.name,
        STATUS_OK,
        fetched=len(result.postings),
        new=saved.new,
        updated=saved.updated,
        unchanged=saved.unchanged,
        skipped=result.skipped,
        failed=result.failed,
    )


def run_all(
    sources: Sequence[Source], client: httpx.Client, budget: DbRequestBudget
) -> list[SourceSummary]:
    summaries = []
    for source in sources:
        try:
            last_run = budget.last_request_at(source.name)
        except Exception:
            logger.exception("Source %s failed: could not read its request history", source.name)
            summaries.append(SourceSummary(source.name, STATUS_FAILED, failed=1))
            continue
        http = Fetcher(source.name, client, budget, max_attempts=source.max_attempts)
        summaries.append(run_source(source, http, last_run, utc_now()))
    return summaries


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sources = select_sources(build_sources(settings), settings.ingest_sources)
    budget = DbRequestBudget({source.name: source.max_requests_per_day for source in sources})
    with new_client() as client:
        summaries = run_all(sources, client, budget)

    for summary in summaries:
        logger.info(summary.line())

    failed = [summary.name for summary in summaries if summary.status == STATUS_FAILED]
    if failed:
        raise SystemExit(f"Failed sources: {', '.join(failed)}")


if __name__ == "__main__":
    main()
