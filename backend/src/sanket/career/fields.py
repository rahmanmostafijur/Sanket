"""Value rules shared by every part of the career profile. Everything here is untrusted input.

Text is stripped and bounded; a NUL character (which PostgreSQL text cannot hold) is refused.
Months are written `YYYY-MM` in the API and stored as the first day of that month. Links must be
http(s) addresses without credentials, and a link typed without a scheme gets `https://`.
"""

import re
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import urlsplit

import pycountry
from pydantic import BeforeValidator, PlainSerializer

MIN_YEAR = 1950
MAX_URL_CHARS = 300
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\d)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def this_month() -> date:
    """The first day of the current month (UTC)."""
    return datetime.now(UTC).date().replace(day=1)


def clean_line(value: object) -> object:
    """Single-line text: whitespace collapsed. Anything but text is left for validation to refuse."""
    if not isinstance(value, str):
        return value
    if _CONTROL.search(value):
        raise ValueError("must not contain control characters")
    return " ".join(value.split())


def clean_block(value: object) -> object:
    """Multi-line text: line breaks kept (at most one blank line), spaces trimmed on each line."""
    if not isinstance(value, str):
        return value
    if _CONTROL.search(value):
        raise ValueError("must not contain control characters")
    lines = [" ".join(line.split()) for line in value.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_month(value: object) -> object:
    """`YYYY-MM` (or a date) to the first day of that month."""
    if isinstance(value, date):
        return value.replace(day=1)
    if not isinstance(value, str):
        return value
    match = _MONTH.match(value.strip())
    if match is None:
        raise ValueError("use the form YYYY-MM, for example 2021-09")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError("the month must be between 01 and 12")
    if year < MIN_YEAR:
        raise ValueError(f"the year must be {MIN_YEAR} or later")
    return date(year, month, 1)


def format_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


Month = Annotated[
    date, BeforeValidator(parse_month), PlainSerializer(format_month, return_type=str)
]


def clean_country(value: object) -> object:
    """An ISO 3166-1 alpha-2 code in upper case, or empty."""
    if not isinstance(value, str):
        return value
    code = " ".join(value.split()).upper()
    if code and (len(code) != 2 or pycountry.countries.get(alpha_2=code) is None):
        raise ValueError("use a two-letter country code such as DE or BD")
    return code


def clean_url(host: str | None = None) -> BeforeValidator:
    """A validator for a link. `host` (such as "github.com") limits it to that site."""

    def check(value: object) -> object:
        if not isinstance(value, str):
            return value
        link = value.strip()
        if not link:
            return ""
        if any(char.isspace() for char in link):
            raise ValueError("a link must not contain spaces")
        if "://" not in link:
            if _OTHER_SCHEME.match(link):
                raise ValueError("use an http or https link")
            link = f"https://{link}"
        try:
            parts = urlsplit(link)
            name = parts.hostname
            parts.port  # noqa: B018  - raises ValueError for a bad port
        except ValueError:
            raise ValueError("this is not a valid link") from None
        if parts.scheme not in ("http", "https") or not name or "." not in name:
            raise ValueError("use an http or https link")
        if parts.username is not None or parts.password is not None:
            raise ValueError("a link must not contain a user name or password")
        if len(link) > MAX_URL_CHARS:
            raise ValueError(f"a link can be at most {MAX_URL_CHARS} characters")
        if host is not None and name != host and not name.endswith(f".{host}"):
            raise ValueError(f"use a {host} link")
        return link

    return BeforeValidator(check)
