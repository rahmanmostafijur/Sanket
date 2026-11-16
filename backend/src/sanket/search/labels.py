"""Labelled queries for search evaluation, read from a JSONL file.

One JSON object per line (blank lines are skipped)::

    {"query": "python backend engineer",
     "relevant": [{"job_ref": "fp1:<64 hex digits>", "grade": 3}, ...],
     "notes": "optional free text"}

`job_ref` is the job's fingerprint (`job.fingerprint`), not its id: ids are assigned by the
database and differ between databases, while the fingerprint is computed from the job's
company, title and location and is the same wherever the job is canonicalised. `grade` is 1
(somewhat relevant), 2 (relevant) or 3 (highly relevant); a job not listed is not relevant.

Loading is strict: an unknown key, a bad grade or reference, a repeated reference or a
repeated query is an error that names the file and the line.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sanket.search.metrics import MAX_GRADE, MIN_GRADE

MAX_QUERY_CHARS = 200
MAX_NOTES_CHARS = 1000
FINGERPRINT_PATTERN = re.compile(r"^fp\d+:[0-9a-f]{64}$")


class LabelError(ValueError):
    """The labelled data file is malformed; the message says where."""


class RelevantJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ref: str = Field(description="The job fingerprint, for example fp1:ab12...")
    grade: int = Field(ge=MIN_GRADE, le=MAX_GRADE)

    @field_validator("job_ref")
    @classmethod
    def _is_a_fingerprint(cls, value: str) -> str:
        if not FINGERPRINT_PATTERN.match(value):
            raise ValueError("job_ref must be a job fingerprint such as fp1:<64 hex digits>")
        return value


class LabelledQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    relevant: list[RelevantJob]
    notes: str | None = Field(default=None, max_length=MAX_NOTES_CHARS)

    @field_validator("query", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("relevant")
    @classmethod
    def _unique_refs(cls, value: list[RelevantJob]) -> list[RelevantJob]:
        refs = [item.job_ref for item in value]
        if len(set(refs)) != len(refs):
            raise ValueError("a job_ref is listed more than once")
        return value

    @property
    def grades(self) -> dict[str, int]:
        return {item.job_ref: item.grade for item in self.relevant}


def _describe(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "line"
        parts.append(f"{where}: {item['msg']}")
    return "; ".join(parts)


def parse_line(text: str) -> LabelledQuery:
    """Parse one JSONL line; raises JSONDecodeError or ValidationError when it is malformed."""
    return LabelledQuery.model_validate(json.loads(text))


def parse_labels(lines: Sequence[str], source: str = "<labels>") -> list[LabelledQuery]:
    queries: list[LabelledQuery] = []
    first_line_of: dict[str, int] = {}
    for number, text in enumerate(lines, 1):
        if not text.strip():
            continue
        try:
            query = parse_line(text)
        except json.JSONDecodeError as error:
            raise LabelError(f"{source}:{number}: not valid JSON ({error.msg})") from error
        except ValidationError as error:
            raise LabelError(f"{source}:{number}: {_describe(error)}") from error
        key = query.query.casefold()
        if key in first_line_of:
            raise LabelError(
                f"{source}:{number}: query {query.query!r} repeats line {first_line_of[key]}"
            )
        first_line_of[key] = number
        queries.append(query)
    if not queries:
        raise LabelError(f"{source}: no labelled queries found")
    return queries


def load_labels(path: Path) -> list[LabelledQuery]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LabelError(f"{path}: cannot read the file ({error})") from error
    # Split on the newline character only: other Unicode line breaks may legally appear
    # inside a JSON string, and a trailing carriage return is plain whitespace to the parser.
    return parse_labels(text.split(chr(10)), str(path))
