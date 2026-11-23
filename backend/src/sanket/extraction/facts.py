"""Structured facts a job board publishes with a posting, for the extraction prompt.

Several sources state the workplace type, employment type or level in fields of their own
(`posting.raw`) rather than in the description, and the remote-only boards never repeat
"remote" in every posting. These facts are shown to the model as labelled header lines, so
it can use what the source states instead of answering "unknown".

`fill_work_mode` is the one deterministic step after the model: when the model still says
"unknown", a workplace type the source states, or a location field that says "remote", is
used. Nothing is inferred beyond what the source itself says.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sanket.extraction.schema import JobExtraction, WorkMode

# Boards that list remote jobs only, so every posting on them is remote.
REMOTE_ONLY_SOURCES = frozenset({"himalayas", "jobicy", "weworkremotely", "remoteok"})
REMOTE_ONLY_NOTE = "Remote (the job board lists remote jobs only)"
# Greenhouse custom fields, by lowercased name.
GREENHOUSE_WORKPLACE = frozenset({"workplace type"})
GREENHOUSE_EMPLOYMENT = frozenset({"employment type", "time type"})
GREENHOUSE_SENIORITY = frozenset({"seniority"})
# Values that say nothing.
EMPTY_VALUES = frozenset({"", "any", "unspecified", "n/a", "none"})
MAX_FACT_CHARS = 100

WORKPLACE_MODES = {
    "remote": WorkMode.REMOTE,
    "hybrid": WorkMode.HYBRID,
    "onsite": WorkMode.ONSITE,
    "inoffice": WorkMode.ONSITE,
}
REMOTE_WORD = re.compile(r"\bremote\b", re.IGNORECASE)
HYBRID_WORD = re.compile(r"\bhybrid\b", re.IGNORECASE)


@dataclass(frozen=True)
class SourceFacts:
    workplace: str | None = None
    employment_type: str | None = None
    seniority: str | None = None

    def lines(self) -> tuple[tuple[str, str], ...]:
        """Header lines, labelled so the model can tell them from the posting's own text."""
        fields = (
            ("Workplace type (from the job board)", self.workplace),
            ("Employment type (from the job board)", self.employment_type),
            ("Seniority (from the job board)", self.seniority),
        )
        return tuple((name, value) for name, value in fields if value)


def _text(value: Any) -> str | None:
    """A plain value as text, lists joined; None for anything empty or meaningless."""
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value if isinstance(item, str | int))
    if not isinstance(value, str | int) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())[:MAX_FACT_CHARS]
    return None if text.lower() in EMPTY_VALUES else text


def _greenhouse_field(raw: Mapping[str, Any], names: frozenset[str]) -> str | None:
    metadata = raw.get("metadata")
    for item in metadata if isinstance(metadata, list) else []:
        if isinstance(item, dict) and str(item.get("name", "")).strip().lower() in names:
            return _text(item.get("value"))
    return None


def _categories(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    categories = raw.get("categories")
    return categories if isinstance(categories, dict) else {}


def source_facts(source: str, raw: Any) -> SourceFacts:
    """What `source` states in its own fields of `raw`; empty for sources without any."""
    data: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
    remote = REMOTE_ONLY_NOTE if source in REMOTE_ONLY_SOURCES else None
    if source == "lever":
        return SourceFacts(
            _text(data.get("workplaceType")), _text(_categories(data).get("commitment"))
        )
    if source == "ashby":
        return SourceFacts(_text(data.get("workplaceType")), _text(data.get("employmentType")))
    if source == "greenhouse":
        return SourceFacts(
            _greenhouse_field(data, GREENHOUSE_WORKPLACE),
            _greenhouse_field(data, GREENHOUSE_EMPLOYMENT),
            _greenhouse_field(data, GREENHOUSE_SENIORITY),
        )
    if source == "himalayas":
        return SourceFacts(remote, _text(data.get("employmentType")), _text(data.get("seniority")))
    if source == "jobicy":
        return SourceFacts(remote, _text(data.get("jobType")), _text(data.get("jobLevel")))
    if source == "weworkremotely":
        return SourceFacts(remote, _text(data.get("type")))
    return SourceFacts(remote)


def stated_work_mode(facts: SourceFacts, location: str | None) -> WorkMode | None:
    """The work mode the source states outright, or None."""
    if facts.workplace:
        key = re.sub(r"[^a-z]", "", facts.workplace.lower().split("(")[0])
        if key in WORKPLACE_MODES:
            return WORKPLACE_MODES[key]
    if location and REMOTE_WORD.search(location) and not HYBRID_WORD.search(location):
        return WorkMode.REMOTE
    return None


def fill_work_mode(
    data: JobExtraction, facts: SourceFacts, location: str | None
) -> JobExtraction:
    """`data`, with an "unknown" work mode replaced by the one the source states."""
    if data.work_mode is not WorkMode.UNKNOWN:
        return data
    stated = stated_work_mode(facts, location)
    return data if stated is None else data.model_copy(update={"work_mode": stated})
