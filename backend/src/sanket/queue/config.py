"""Queue configuration and the retry schedule derived from it."""

import math
from dataclasses import dataclass

from sanket.config import Settings

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class QueueConfig:
    queue_name: str = "sanket"
    # Attempts per task in total, the first run included.
    max_attempts: int = 5
    backoff_base_seconds: float = 30.0
    backoff_factor: float = 2.0
    backoff_max_seconds: float = 3600.0
    task_timeout_seconds: int = 600
    dead_letter_ttl_seconds: int = 30 * SECONDS_PER_DAY


def config_from_settings(config: Settings) -> QueueConfig:
    return QueueConfig(
        queue_name=config.queue_name,
        max_attempts=config.queue_max_attempts,
        backoff_base_seconds=config.queue_backoff_base_seconds,
        backoff_factor=config.queue_backoff_factor,
        backoff_max_seconds=config.queue_backoff_max_seconds,
        task_timeout_seconds=config.queue_task_timeout_seconds,
        dead_letter_ttl_seconds=config.queue_dead_letter_ttl_days * SECONDS_PER_DAY,
    )


def backoff_schedule(cfg: QueueConfig) -> list[int]:
    """Seconds to wait before each retry: `base * factor ** n`, capped, whole seconds.

    There is one entry per retry, so `max_attempts - 1` of them.
    """
    delays = []
    for retry in range(cfg.max_attempts - 1):
        delay = min(cfg.backoff_base_seconds * cfg.backoff_factor**retry, cfg.backoff_max_seconds)
        delays.append(max(1, math.ceil(delay)))
    return delays
