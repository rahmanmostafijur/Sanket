"""The searchable document of a job and the text and hashes derived from it.

Everything here is pure: no database, no clock, no network. The same inputs always give the
same document, text and hashes, which is what makes the hash gates in the indexing worker
(`sanket.indexing.service`) safe: a job is written again only when something it is built
from changed.

A job is described by its canonical fields (title, company, location), by the successful
extraction of its representative posting (seniority, work mode, employment type, skills,
minimum years of experience) and by a bounded excerpt of that posting's description. Jobs
whose representative posting has neither an extraction nor a description are still indexed
from title, company and location alone.

Embedding text, one line per field that is present, in this order::

    Title: <title>
    Company: <company>
    Location: <location>
    Seniority: <senior>                  (left out when unknown)
    Work mode: <remote>                  (left out when unknown)
    Employment type: <full time>         (left out when unknown)
    Experience: <3+ years>
    Skills: <Python, PostgreSQL>

    Description:
    <excerpt of the description, HTML removed, cut at the configured length>

Salary is not embedded: numbers add noise to semantic similarity, and pay is a filter rather
than a topic. Full-text weights: title A; company, skills, seniority, work mode and
employment type B; location C; description excerpt D.

Changing any of this changes the hashes, so every job is indexed again on the next run.
That is intended; bump `DOCUMENT_FORMAT_VERSION` when the format changes on purpose so the
change is visible in the hashes even when the text of some jobs happens not to move.
"""

import hashlib
import json
from dataclasses import dataclass

from sanket.extraction.prompt import html_to_text
from sanket.extraction.schema import JobExtraction

# Bump when the embedding text or the full-text field layout changes.
DOCUMENT_FORMAT_VERSION = 1
# Text search configuration. `simple` lowercases and splits on word boundaries without
# stemming or stop words, so it behaves the same for English, Swedish and Bengali text.
TEXT_SEARCH_CONFIG = "simple"

# Bounds on the canonical fields, which are free text from the sources.
MAX_TITLE_CHARS = 300
MAX_COMPANY_CHARS = 200
MAX_LOCATION_CHARS = 300

UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobFields:
    """The canonical fields of a job, as stored in the `job` table."""

    title: str
    company: str
    location: str | None


@dataclass(frozen=True)
class PostingFields:
    """What the document needs from the representative posting."""

    description: str | None


@dataclass(frozen=True)
class SearchDocument:
    title: str
    company: str
    location: str | None
    seniority: str | None
    work_mode: str | None
    employment_type: str | None
    min_years_experience: int | None
    skills: tuple[str, ...]
    description: str

    @property
    def is_empty(self) -> bool:
        """Nothing at all to search or embed."""
        return not (self.title or self.company or self.location or self.description)


@dataclass(frozen=True)
class WeightedText:
    """The text of each full-text weight class, for `setweight(to_tsvector(...), 'A'..'D')`."""

    a: str
    b: str
    c: str
    d: str


def _collapse(value: str | None, max_chars: int) -> str:
    text = " ".join((value or "").split())
    return text[:max_chars].rstrip()


def _label(value: str | None) -> str | None:
    """An enum value as words, or None when it says nothing ("unknown" or missing)."""
    if value is None or value == UNKNOWN:
        return None
    return value.replace("_", " ")


def excerpt(description: str | None, max_chars: int) -> str:
    """Plain text of the description (HTML removed, line per block), cut at `max_chars`."""
    if not description:
        return ""
    return html_to_text(description)[:max_chars].rstrip()


def build_search_document(
    job: JobFields,
    extraction: JobExtraction | None,
    posting: PostingFields | None,
    max_description_chars: int,
) -> SearchDocument:
    """Build the document of one job. `extraction` and `posting` may be missing."""
    return SearchDocument(
        title=_collapse(job.title, MAX_TITLE_CHARS),
        company=_collapse(job.company, MAX_COMPANY_CHARS),
        location=_collapse(job.location, MAX_LOCATION_CHARS) or None,
        seniority=_label(extraction.seniority.value) if extraction else None,
        work_mode=_label(extraction.work_mode.value) if extraction else None,
        employment_type=_label(extraction.employment_type.value) if extraction else None,
        min_years_experience=extraction.min_years_experience if extraction else None,
        skills=tuple(extraction.skills) if extraction else (),
        description=excerpt(posting.description if posting else None, max_description_chars),
    )


def build_embedding_text(doc: SearchDocument) -> str:
    """The text sent to the embedding model (format in the module docstring)."""
    lines = [
        ("Title", doc.title),
        ("Company", doc.company),
        ("Location", doc.location),
        ("Seniority", doc.seniority),
        ("Work mode", doc.work_mode),
        ("Employment type", doc.employment_type),
        ("Experience", _years(doc.min_years_experience)),
        ("Skills", ", ".join(doc.skills)),
    ]
    text = "\n".join(f"{name}: {value}" for name, value in lines if value)
    if doc.description:
        text = f"{text}\n\nDescription:\n{doc.description}"
    return text


def _years(years: int | None) -> str | None:
    return None if years is None else f"{years}+ years"


def build_weighted_text(doc: SearchDocument) -> WeightedText:
    """Split the document into the four full-text weight classes."""
    secondary = [doc.company, *doc.skills, doc.seniority, doc.work_mode, doc.employment_type]
    return WeightedText(
        a=doc.title,
        b=" ".join(part for part in secondary if part),
        c=doc.location or "",
        d=" ".join(doc.description.split()),
    )


def _digest(parts: list[object]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def search_hash(doc: SearchDocument) -> str:
    """Hash of everything the stored tsvector is built from."""
    weighted = build_weighted_text(doc)
    return _digest(
        [
            DOCUMENT_FORMAT_VERSION,
            TEXT_SEARCH_CONFIG,
            weighted.a,
            weighted.b,
            weighted.c,
            weighted.d,
        ]
    )


def embedding_hash(text: str, model_name: str, model_version: str, dimension: int) -> str:
    """Hash of everything a stored embedding depends on: text, model and format."""
    return _digest([DOCUMENT_FORMAT_VERSION, model_name, model_version, dimension, text])
