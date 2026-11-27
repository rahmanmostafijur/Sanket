"""Turn the bytes of a CV into text, in memory.

The kind of file is decided by its content (magic bytes and, for DOCX, the parts of the zip
archive), never by its name or declared type. PDF and DOCX only. Everything happens on bytes
already in memory: nothing is written to disk, and nothing from the file is put in an error
message or a log line, because a CV is personal data.

Limits keep a hostile file cheap: the size is capped before anything is parsed, a PDF is read
for its first pages only, a DOCX archive may not expand past a fixed size, and the extracted
text is cut to what the language model should be sent.
"""

import io
import re
import zipfile
from enum import StrEnum

from docx import Document
from pypdf import PdfReader

MAX_CV_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000
# What is sent to the model. A CV is a few pages; more than this is not a CV.
MAX_CV_CHARS = 30_000
# Below this there is nothing to read: an image-only (scanned) file or an empty one.
MIN_CV_CHARS = 80

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_PARTS = ("[Content_Types].xml", "word/document.xml")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUN = re.compile(r"\n{3,}")


class CvError(Exception):
    """A CV that cannot be used. The message is safe to show: it never quotes the file."""


class CvTypeError(CvError):
    """Not a PDF or a DOCX, whatever the file is called."""


class CvTooLargeError(CvError):
    """Larger than MAX_CV_BYTES."""


class CvUnreadableError(CvError):
    """A PDF or DOCX with no text that can be read (scanned, empty, protected or damaged)."""


class CvFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


def detect_format(data: bytes) -> CvFormat | None:
    """The format by content, or None. A DOCX is a zip with the two parts every one has."""
    if data.startswith(_PDF_MAGIC):
        return CvFormat.PDF
    if not data.startswith(_ZIP_MAGIC):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return None
    return CvFormat.DOCX if all(part in names for part in _DOCX_PARTS) else None


def _check_archive(data: bytes) -> None:
    """Refuse a zip that would expand into too much memory (a zip bomb)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_DOCX_ENTRIES or (
            sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES
        ):
            raise CvUnreadableError("this document is too large to read")


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise CvUnreadableError("this PDF is password protected")
    pages = reader.pages[:MAX_PDF_PAGES]
    return "\n".join((page.extract_text() or "") for page in pages)


def _docx_text(data: bytes) -> str:
    _check_archive(data)
    document = Document(io.BytesIO(data))
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = dict.fromkeys(cell.text.strip() for cell in row.cells)
            lines.append(" | ".join(cell for cell in cells if cell))
    return "\n".join(lines)


def _tidy(text: str) -> str:
    """No control characters, trailing spaces trimmed, blank-line runs shortened, bounded."""
    text = _CONTROL.sub("", text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()[:MAX_CV_CHARS]


def read_cv(data: bytes) -> str:
    """The text of a PDF or DOCX CV. Raises a `CvError` subclass for anything else."""
    if len(data) > MAX_CV_BYTES:
        raise CvTooLargeError("the file is larger than 5 MB")
    kind = detect_format(data)
    if kind is None:
        raise CvTypeError("only PDF and DOCX files are supported")
    try:
        raw = _pdf_text(data) if kind is CvFormat.PDF else _docx_text(data)
    except CvError:
        raise
    except Exception:  # noqa: BLE001
        # Parsers raise many kinds of error on damaged input; none is worth showing.
        raise CvUnreadableError(f"this {kind.value.upper()} could not be read") from None
    text = _tidy(raw)
    if len(text) < MIN_CV_CHARS:
        raise CvUnreadableError(
            "no readable text found; a scanned or image-only file cannot be read, "
            "use a text-based PDF or a DOCX"
        )
    return text
