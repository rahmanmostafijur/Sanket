"""Helpers for source adapter tests: recorded fixtures and a network-free Fetcher."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from sanket.sources.http import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


def load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load_json(name: str):
    return json.loads(load_bytes(name))


def make_fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    budget=None,
    sleeps: list[float] | None = None,
    max_attempts: int = 1,
) -> Fetcher:
    """A Fetcher whose requests go to `handler`; sleeps are recorded, never waited."""
    recorded = sleeps if sleeps is not None else []
    kwargs = {"budget": budget} if budget is not None else {}
    return Fetcher(
        "test",
        httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=max_attempts,
        sleep=recorded.append,
        **kwargs,
    )


def json_handler(payload) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json=payload)
