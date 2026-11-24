"""Work through the extraction backlog within a rate, a daily cap and a cost cap.

`python -m sanket.extract_backfill [--limit N] [--max-cost-usd X] [--no-reindex]` extracts
pending postings newest first (the same hash gate as the scheduled runner, so an unchanged
posting is never sent twice), paced at EXTRACT_BACKFILL_RPM and waiting out rate limits. It
stops cleanly, before the next posting, when:

- the estimated cost would pass EXTRACT_BACKFILL_MAX_COST_USD (tokens times the prices in
  EXTRACTION_INPUT_USD_PER_MTOK / EXTRACTION_OUTPUT_USD_PER_MTOK);
- EXTRACT_BACKFILL_DAILY_CAP postings were sent this UTC day (counted in Redis when REDIS_URL
  is set, so a restarted run respects it; otherwise per run);
- the provider's daily quota is used up, or several provider errors come in a row.

It reports postings by outcome, tokens, the estimated cost and how many postings remain
pending. Extracted jobs are indexed again in batches (INDEX_AFTER_EXTRACTION).
"""

import argparse
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from redis import Redis
from sqlalchemy import Engine, func, select

from sanket.config import Settings, settings
from sanket.db import engine
from sanket.extraction.llm import (
    BackoffLlmClient,
    ChatMessage,
    GeminiClient,
    LlmClient,
    LlmResponse,
)
from sanket.extraction.reindex import reindexer_from_settings
from sanket.extraction.runner import (
    MAX_CONSECUTIVE_PROVIDER_ERRORS,
    ExtractionConfig,
    Outcome,
    config_from_settings,
    extract_posting,
    find_pending,
    is_pending,
)
from sanket.observability.logs import configure_logging

TOKENS_PER_MILLION = 1_000_000
REINDEX_BATCH = 50
DAILY_KEY_PREFIX = "sanket:extract_backfill:day:"
DAILY_KEY_TTL_SECONDS = 2 * 24 * 3600

logger = logging.getLogger(__name__)


class MeteredLlmClient:
    """Passes calls through and adds up the tokens of every response, repairs included."""

    def __init__(self, inner: LlmClient) -> None:
        self.model = inner.model
        self._inner = inner
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict
    ) -> LlmResponse:
        response = self._inner.generate(system_prompt, messages, response_schema)
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        return response


@dataclass(frozen=True)
class Prices:
    input_usd_per_mtok: float
    output_usd_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        ) / TOKENS_PER_MILLION


class DailyCounter(Protocol):
    def used(self) -> int: ...

    def add(self) -> None: ...


@dataclass
class LocalDailyCounter:
    """Counts within this run only (no Redis)."""

    count: int = 0

    def used(self) -> int:
        return self.count

    def add(self) -> None:
        self.count += 1


class RedisDailyCounter:
    """The UTC day's count in Redis, shared by every run on that day."""

    def __init__(self, redis: Redis, today: Callable[[], str]) -> None:
        self._redis = redis
        self._today = today

    def _key(self) -> str:
        return DAILY_KEY_PREFIX + self._today()

    def used(self) -> int:
        value = self._redis.get(self._key())
        return int(value) if isinstance(value, bytes | str | int) else 0

    def add(self) -> None:
        key = self._key()
        self._redis.incr(key)
        self._redis.expire(key, DAILY_KEY_TTL_SECONDS)


@dataclass(frozen=True)
class Limits:
    max_postings: int
    max_cost_usd: float
    daily_cap: int


@dataclass
class BackfillReport:
    counts: Counter[Outcome] = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    stop_reason: str = "batch done"
    remaining: int = 0

    @property
    def attempted(self) -> int:
        return sum(self.counts.values()) - self.counts[Outcome.SKIPPED]


def _stop_reason(report: BackfillReport, limits: Limits, counter: DailyCounter) -> str | None:
    """Why the next posting must not be sent, or None."""
    if counter.used() >= limits.daily_cap:
        return f"daily cap of {limits.daily_cap} postings reached"
    # Stop if one more posting at the average cost so far would pass the cap.
    average = report.cost_usd / report.attempted if report.attempted else 0.0
    if report.cost_usd + average > limits.max_cost_usd:
        return f"cost cap of {limits.max_cost_usd:.2f} USD reached"
    return None


def _after_posting(
    report: BackfillReport, client: MeteredLlmClient, prices: Prices, outcome: Outcome
) -> None:
    report.counts[outcome] += 1
    report.input_tokens, report.output_tokens = client.input_tokens, client.output_tokens
    report.calls = client.calls
    report.cost_usd = prices.cost(client.input_tokens, client.output_tokens)


def run_backfill(
    client: MeteredLlmClient,
    cfg: ExtractionConfig,
    limits: Limits,
    prices: Prices,
    counter: DailyCounter,
    on_extracted: Callable[[Sequence[int]], None] | None = None,
    quota_exhausted: Callable[[], bool] = lambda: False,
    db_engine: Engine = engine,
) -> BackfillReport:
    report = BackfillReport()
    extracted: list[int] = []
    consecutive_errors = 0
    for posting_id in find_pending(cfg, limits.max_postings, db_engine):
        reason = _stop_reason(report, limits, counter)
        if reason:
            report.stop_reason = reason
            break
        counter.add()
        outcome = extract_posting(posting_id, client, cfg, db_engine)
        _after_posting(report, client, prices, outcome)
        extracted = [*extracted, posting_id] if outcome is Outcome.OK else extracted
        if on_extracted is not None and len(extracted) >= REINDEX_BATCH:
            on_extracted(extracted)
            extracted = []
        consecutive_errors = consecutive_errors + 1 if outcome is Outcome.PROVIDER_ERROR else 0
        if quota_exhausted():
            report.stop_reason = "the provider's daily quota is used up"
            break
        if consecutive_errors >= MAX_CONSECUTIVE_PROVIDER_ERRORS:
            report.stop_reason = f"{consecutive_errors} provider errors in a row"
            break
    if on_extracted is not None and extracted:
        on_extracted(extracted)
    report.remaining = count_pending(cfg, db_engine)
    return report


def count_pending(cfg: ExtractionConfig, db_engine: Engine = engine) -> int:
    with db_engine.connect() as conn:
        return int(conn.execute(select(func.count()).where(is_pending(cfg))).scalar_one())


def _daily_counter(config: Settings) -> DailyCounter:
    if config.redis_url is None:
        logger.info("REDIS_URL is not set: the daily cap is counted for this run only")
        return LocalDailyCounter()
    from sanket.queue.connection import redis_connection

    return RedisDailyCounter(redis_connection(config), lambda: datetime.now(UTC).date().isoformat())


def _log_report(report: BackfillReport, model: str) -> None:
    logger.info(
        "extract backfill summary model=%s %s calls=%d input_tokens=%d output_tokens=%d "
        "estimated_cost_usd=%.4f remaining_pending=%d stop=%s",
        model,
        " ".join(f"{outcome.value}={report.counts.get(outcome, 0)}" for outcome in Outcome),
        report.calls,
        report.input_tokens,
        report.output_tokens,
        report.cost_usd,
        report.remaining,
        report.stop_reason,
    )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Extract the pending backlog within caps.")
    parser.add_argument("--limit", type=int, default=settings.extraction_batch_limit)
    parser.add_argument(
        "--max-cost-usd", type=float, default=settings.extract_backfill_max_cost_usd
    )
    parser.add_argument("--no-reindex", action="store_true", help="do not index jobs again")
    args = parser.parse_args()
    if settings.gemini_api_key is None:
        raise SystemExit("GEMINI_API_KEY is not set")
    cfg = config_from_settings(settings)
    backoff = BackoffLlmClient(
        GeminiClient(
            settings.gemini_api_key, cfg.model, requests_per_minute=settings.extract_backfill_rpm
        )
    )
    client = MeteredLlmClient(backoff)
    report = run_backfill(
        client,
        cfg,
        Limits(args.limit, args.max_cost_usd, settings.extract_backfill_daily_cap),
        Prices(settings.extraction_input_usd_per_mtok, settings.extraction_output_usd_per_mtok),
        _daily_counter(settings),
        on_extracted=None if args.no_reindex else reindexer_from_settings(settings),
        quota_exhausted=lambda: backoff.daily_quota_exhausted,
    )
    _log_report(report, cfg.model)


if __name__ == "__main__":
    main()
