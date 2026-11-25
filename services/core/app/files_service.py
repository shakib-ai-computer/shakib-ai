"""File upload support: allowlist, size cap, on-disk storage, text extraction.

Extraction happens once, at upload time, from the in-memory bytes:

- PDF  -> pypdf page text
- DOCX -> python-docx paragraph text
- TXT / Markdown -> decoded as UTF-8

Anything the extractor cannot read raises :class:`ExtractionError` with a
short, user-safe message — internal exception text and stack traces never
reach the API response. The original bytes are stored under
``data/uploads/<scope>/<document_id>`` where ``<scope>`` is the owner's
user id, or ``anon`` for anonymous uploads.
"""

from __future__ import annotations

import io
from pathlib import Path

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
TEXT_PREVIEW_LIMIT = 50_000  # chars served by GET /api/files/{id}

UPLOADS_DIR = Path(__file__).resolve().parents[1] / "data" / "uploads"

# Extension allowlist -> canonical MIME type. The client's declared
# content type is never trusted; the extension decides.
ALLOWED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ExtractionError(Exception):
    """The uploaded file could not be read as its declared type."""


def scope_name(user_id: int | None) -> str:
    return str(user_id) if user_id is not None else "anon"


def storage_path(user_id: int | None, document_id: int) -> Path:
    return UPLOADS_DIR / scope_name(user_id) / str(document_id)


def write_bytes(user_id: int | None, document_id: int, data: bytes) -> Path:
    path = storage_path(user_id, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def delete_bytes(user_id: int | None, document_id: int) -> None:
    """Best-effort removal of the stored bytes (missing file is fine)."""
    try:
        storage_path(user_id, document_id).unlink(missing_ok=True)
    except OSError:
        pass


def extract_text(extension: str, data: bytes) -> str:
    """Extract plain text from ``data`` according to its allowlisted type."""
    if extension == ".pdf":
        return _extract_pdf(data)
    if extension == ".docx":
        return _extract_docx(data)
    # .txt / .md
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            "text file is not valid UTF-8 and could not be read"
        ) from exc


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PyPdfError, ValueError, OSError) as exc:
        raise ExtractionError(
            "PDF could not be read (corrupt or unsupported PDF file)"
        ) from exc


def _extract_docx(data: bytes) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, ValueError, OSError, KeyError) as exc:
        raise ExtractionError(
            "DOCX could not be read (corrupt or unsupported DOCX file)"
        ) from exc
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
