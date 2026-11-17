"""Small parsing helpers shared by the source adapters."""

import html
from collections.abc import Iterable
from datetime import UTC, datetime, tzinfo
from email.utils import parsedate_to_datetime

MILLISECONDS_PER_SECOND = 1000


def clean_text(value: str | None) -> str | None:
    """Unescape HTML entities and strip whitespace; empty becomes None."""
    if value is None:
        return None
    text = html.unescape(value).strip()
    return text or None


def join_nonempty(parts: Iterable[str | None], separator: str = ", ") -> str | None:
    kept = [part.strip() for part in parts if part and part.strip()]
    return separator.join(kept) or None


def from_epoch_seconds(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def from_epoch_milliseconds(value: float | None) -> datetime | None:
    if value is None:
        return None
    return from_epoch_seconds(value / MILLISECONDS_PER_SECOND)


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are taken as UTC."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_local_datetime(value: str | None, zone: tzinfo) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are taken as wall-clock time in `zone`."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed


def parse_rfc822_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def salary_text(
    minimum: float | None,
    maximum: float | None,
    currency: str | None,
    period: str | None,
) -> str | None:
    """Format a structured salary as text, for example "80000-165000 USD per year"."""
    if not minimum and not maximum:
        return None
    amount = "-".join(_format_number(value) for value in (minimum, maximum) if value)
    return join_nonempty([amount, currency, f"per {period}" if period else None], " ")
