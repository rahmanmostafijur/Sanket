"""The hook that tells the rest of the system about a new match.

A match is new when its row is first inserted and when a withdrawn match becomes active again.
The matcher calls `notify` after the transaction that wrote the match has committed, so a
subscriber that reads the database always finds the row. The persisted row is the source of
truth: a notifier that raises is logged and never fails or retries the matching, and the
match then keeps `notified_at` NULL, which is how a later sweep can find what was missed.

The default does nothing. The live feed (the next phase) provides an implementation that
publishes to Redis; whatever it does must be quick and must not assume it is called once per
match (a crash between the commit and the call loses a notification, a retry of the whole
task repeats none because unchanged matches are not new).
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class MatchRecord:
    """A persisted match, as handed to the notifier."""

    match_id: int
    profile_id: int
    owner_id: str
    job_id: int
    score: float
    components: dict[str, Any]
    # True when a withdrawn match became active again, False for a first match.
    reactivated: bool


class MatchNotifier(Protocol):
    def notify(self, match: MatchRecord) -> None: ...


class NoopNotifier:
    def notify(self, match: MatchRecord) -> None:
        return None
