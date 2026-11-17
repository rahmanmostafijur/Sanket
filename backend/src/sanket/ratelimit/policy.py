"""What each bucket allows, taken from the settings."""

from dataclasses import dataclass
from typing import Literal

from sanket.config import Settings

Bucket = Literal["default", "search"]


@dataclass(frozen=True)
class RateLimits:
    window_seconds: int = 60
    default_requests: int = 120
    search_requests: int = 30
    trusted_proxy_hops: int = 0

    def for_bucket(self, bucket: Bucket) -> int:
        return self.search_requests if bucket == "search" else self.default_requests


def limits_from_settings(config: Settings) -> RateLimits:
    return RateLimits(
        window_seconds=config.rate_limit_window_seconds,
        default_requests=config.rate_limit_default_requests,
        search_requests=config.rate_limit_search_requests,
        trusted_proxy_hops=config.trusted_proxy_hops,
    )
