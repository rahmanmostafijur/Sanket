"""The message published for a new match, and the channel it goes to.

The message is a pointer, not the match: ids and the score, nothing owner-private (no owner id,
no score components, no job text). The stream reads the persisted row for what it sends, so a
subscriber always shows what the database says, and a message from a match that has since
been withdrawn or deleted shows nothing.
"""

import json
from dataclasses import dataclass

from sanket.matching.notify import MatchRecord


@dataclass(frozen=True)
class MatchEvent:
    match_id: int
    profile_id: int
    job_id: int
    score: float
    # True when a withdrawn match became active again.
    reactivated: bool


def channel_for(prefix: str, profile_id: int) -> str:
    return f"{prefix}:{profile_id}"


def event_from_record(record: MatchRecord) -> MatchEvent:
    return MatchEvent(
        match_id=record.match_id,
        profile_id=record.profile_id,
        job_id=record.job_id,
        score=record.score,
        reactivated=record.reactivated,
    )


def encode(event: MatchEvent) -> str:
    return json.dumps(
        {
            "match_id": event.match_id,
            "profile_id": event.profile_id,
            "job_id": event.job_id,
            "score": event.score,
            "reactivated": event.reactivated,
        },
        separators=(",", ":"),
    )


def decode(raw: bytes | str) -> MatchEvent:
    """Parse a published message; raises ValueError for anything that is not one."""
    try:
        data = json.loads(raw)
        return MatchEvent(
            match_id=_int(data["match_id"]),
            profile_id=_int(data["profile_id"]),
            job_id=_int(data["job_id"]),
            score=float(data["score"]),
            reactivated=bool(data["reactivated"]),
        )
    except (TypeError, KeyError, ValueError) as error:
        raise ValueError("not a match event") from error


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer")
    return value
