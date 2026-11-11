import xml.etree.ElementTree as ET
from datetime import timedelta

from sanket.sources.base import FetchResult, NormalizedPosting, convert_items
from sanket.sources.fields import clean_text, join_nonempty, parse_rfc822_datetime
from sanket.sources.http import Fetcher

URL = "https://weworkremotely.com/remote-jobs.rss"
TITLE_SEPARATOR = ": "


class WeWorkRemotelySource:
    """We Work Remotely public RSS feed (latest ~100 jobs). Terms: link back to WWR."""

    name = "weworkremotely"
    max_requests_per_day: int | None = 12
    max_attempts = 3
    min_interval: timedelta | None = None

    def fetch(self, http: Fetcher) -> FetchResult:
        items = parse_feed(http.get(URL).content)
        postings, failed = convert_items(self.name, items, to_posting)
        return FetchResult(postings, failed=failed)


def parse_feed(content: bytes) -> list[dict]:
    """Return each <item> as a dict of its plain child elements (namespaced ones skipped)."""
    root = ET.fromstring(content)
    return [
        {child.tag: (child.text or "").strip() for child in item if "}" not in child.tag}
        for item in root.iterfind("./channel/item")
    ]


def _split_title(value: str) -> tuple[str | None, str]:
    """WWR titles are "Company: Job title"."""
    company, separator, title = value.partition(TITLE_SEPARATOR)
    if not separator:
        return None, value
    return company.strip() or None, title.strip()


def to_posting(item: dict) -> NormalizedPosting:
    company, title = _split_title(clean_text(item["title"]) or "")
    return NormalizedPosting(
        source="weworkremotely",
        source_id=item["guid"],
        url=item["link"],
        title=title,
        raw=item,
        company=company,
        location=join_nonempty([item.get("region"), item.get("country"), item.get("state")]),
        description=item.get("description") or None,
        published_at=parse_rfc822_datetime(item.get("pubDate")),
    )
