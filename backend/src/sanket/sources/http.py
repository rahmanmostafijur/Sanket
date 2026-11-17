import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx

USER_AGENT = "Sanket/0.1.0 (github.com/rahmanmostafijur/Sanket)"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
DEFAULT_MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 60.0
TOO_MANY_REQUESTS = 429
SERVER_ERROR_MIN = 500

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when a source has used its request budget for the current UTC day."""


class RequestBudget(Protocol):
    def spend(self, source: str) -> None:
        """Record one request for the source, or raise BudgetExceededError."""
        ...


class UnlimitedBudget:
    def spend(self, source: str) -> None:
        return None


def new_client(timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout)


def is_retryable_status(status_code: int) -> bool:
    return status_code == TOO_MANY_REQUESTS or status_code >= SERVER_ERROR_MIN


def backoff_seconds(attempt: int, jitter: Callable[[], float] = random.random) -> float:
    base = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
    return min(base + jitter(), MAX_BACKOFF_SECONDS)


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Return the Retry-After delay in seconds, capped, or None if absent or not numeric."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


@dataclass
class Fetcher:
    """GET with a request budget and retries on network errors, 429 and 5xx only."""

    source: str
    client: httpx.Client
    budget: RequestBudget = field(default_factory=UnlimitedBudget)
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    sleep: Callable[[float], None] = time.sleep

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._spend(last_error)
            is_last = attempt == self.max_attempts
            try:
                response = self.client.get(url, params=params, headers=headers)
            except httpx.TransportError as error:
                if is_last:
                    raise
                last_error = error
                self._wait(attempt, backoff_seconds(attempt), repr(error))
                continue
            if is_last or not is_retryable_status(response.status_code):
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code}", request=response.request, response=response
            )
            delay = retry_after_seconds(response) or backoff_seconds(attempt)
            self._wait(attempt, delay, f"HTTP {response.status_code}")
        raise ValueError(f"{self.source}: max_attempts must be at least 1")

    def _spend(self, last_error: Exception | None) -> None:
        """Spend one request; if the budget runs out mid-retry, report the real failure."""
        try:
            self.budget.spend(self.source)
        except BudgetExceededError as budget_error:
            if last_error is None:
                raise
            raise last_error from budget_error

    def _wait(self, attempt: int, delay: float, reason: str) -> None:
        logger.warning(
            "%s: attempt %d of %d failed (%s), retrying in %.1fs",
            self.source,
            attempt,
            self.max_attempts,
            reason,
            delay,
        )
        self.sleep(delay)
