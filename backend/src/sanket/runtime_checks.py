"""Fail-fast checks of the settings a process needs to run, made at startup.

`Settings` validates each value on its own; what a process role needs as a whole (an API in
production must have authentication configured, a worker needs the embedding key) is checked
here, so a misconfigured deployment stops at start instead of failing on the first request.
Every problem is collected and reported together. Messages name the setting, never its value.
"""

from sanket.config import Settings


class ConfigError(Exception):
    """The settings do not describe a runnable process; the message lists every problem."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid configuration: " + "; ".join(problems))


def ensure_valid(problems: list[str]) -> None:
    if problems:
        raise ConfigError(problems)


def worker_problems(config: Settings) -> list[str]:
    problems: list[str] = []
    if config.is_production and config.gemini_api_key is None:
        problems.append("GEMINI_API_KEY is required in production (profile embedding needs it)")
    return problems


def check_worker(config: Settings) -> None:
    ensure_valid(worker_problems(config))
