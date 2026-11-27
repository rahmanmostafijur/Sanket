"""Fake CVs and a scripted language model for the CV import tests.

Everything is invented ("Ada Example") and built in memory: a PDF is written by hand from a
few objects, a DOCX with python-docx, so no file is needed and no real person's data is used.
"""

import io
import json
import zipfile
from collections.abc import Sequence
from typing import Any

from docx import Document

from sanket.extraction.llm import ChatMessage, LlmResponse

SAMPLE_LINES = [
    "Ada Example",
    "Backend Engineer",
    "Berlin, Germany",
    "Summary",
    "Backend engineer with six years of experience building APIs and data pipelines in Python.",
    "Experience",
    "Senior Backend Engineer, Example Corp (2021 - present)",
    "Built REST services with Python, FastAPI and PostgreSQL, deployed on Kubernetes.",
    "Backend Engineer, Sample GmbH (2018 - 2021)",
    "Skills",
    "Python, FastAPI, PostgreSQL, Docker, Kubernetes, Redis, Terraform",
    "Looking for remote roles in Germany or Sweden.",
]

SAMPLE_ANSWER: dict[str, Any] = {
    "personal": {
        "full_name": "Ada Example",
        "headline": "Backend Engineer",
        "location": "Berlin, Germany",
        "summary": "Backend engineer with six years of experience building APIs.",
    },
    "profile": {
        "desired_titles": ["Backend Engineer"],
        "required_skills": ["Python", "PostgreSQL"],
        "preferred_skills": ["FastAPI", "Docker", "Kubernetes", "Redis", "Terraform"],
        "seniorities": ["senior"],
        "work_modes": ["remote"],
        "employment_types": [],
        "countries": ["DE", "SE"],
        "locations": [],
        "summary": "",
    },
}

LINES_PER_PAGE = 45


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(lines: Sequence[str]) -> str:
    if not lines:
        return ""
    shown = " ".join(f"({_escape(line)}) Tj T*" for line in lines)
    return f"BT /F1 11 Tf 50 760 Td 14 TL {shown} ET"


def make_pdf(lines: Sequence[str] = SAMPLE_LINES) -> bytes:
    """A valid PDF whose text is `lines`; with no lines it has a page and no text, like a scan."""
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[]]
    font_id = 3 + 2 * len(pages)
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids ["
        + " ".join(f"{3 + 2 * n} 0 R" for n in range(len(pages)))
        + f"] /Count {len(pages)} >>",
        font_id: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for n, page in enumerate(pages):
        page_id, content_id = 3 + 2 * n, 4 + 2 * n
        stream = _page_stream(page)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    count = max(objects) + 1
    out.write(f"xref\n0 {count}\n0000000000 65535 f \n".encode("latin-1"))
    for number in range(1, count):
        out.write(f"{offsets[number]:010d} 00000 n \n".encode("latin-1"))
    out.write(
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    )
    return out.getvalue()


def make_docx(
    paragraphs: Sequence[str] = SAMPLE_LINES, table: Sequence[Sequence[str]] = ()
) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def make_zip_bomb_docx(expanded_bytes: int) -> bytes:
    """A DOCX whose archive expands to `expanded_bytes`, from a few kilobytes of zeros."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/padding.bin", b"\0" * expanded_bytes)
    return out.getvalue()


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
OLD_WORD_BYTES = bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 512
PLAIN_TEXT = ("Ada Example. Backend engineer. Python, PostgreSQL. " * 5).encode()


def plain_zip() -> bytes:
    """A zip that is not a DOCX."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("notes.txt", "Ada Example")
    return out.getvalue()


class ScriptedLlm:
    """A language model that answers from a script: JSON text, a dict (sent as JSON), or an
    exception to raise. Records every call so tests can read what the model was sent."""

    model = "scripted"

    def __init__(self, *answers: str | dict[str, Any] | Exception) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def generate(
        self, system_prompt: str, messages: Sequence[ChatMessage], response_schema: dict[str, Any]
    ) -> LlmResponse:
        self.calls.append((system_prompt, list(messages)))
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, Exception):
            raise answer
        return LlmResponse(text=answer if isinstance(answer, str) else json.dumps(answer))
