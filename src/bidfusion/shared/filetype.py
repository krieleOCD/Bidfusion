"""Shared, provider-free file-type detection from raw bytes.

Extracted from :mod:`bidfusion.security.preflight` so the Security Gate's
deterministic preflight and upload quarantine
(:mod:`bidfusion.bidrun.quarantine`) use exactly one magic-byte detection
implementation — not two that could silently drift apart. Detection here
establishes *identity* (what does this content actually look like), never
a security or acceptance verdict; policy on top of it lives in each
caller (preflight checks, the upload policy allowlist).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PLAIN_TEXT_MIME = "text/plain"
CSV_MIME = "text/csv"
PNG_MIME = "image/png"
JPEG_MIME = "image/jpeg"
ZIP_MIME = "application/zip"
OLE_MIME = "application/x-ole-storage"
UNKNOWN_MIME = "application/octet-stream"

OFFICE_MIME_TYPES = frozenset({DOCX_MIME, XLSX_MIME, PPTX_MIME})

#: Extension -> content types that legitimately match it. Shared so an
#: extension/content mismatch check is defined exactly once.
EXTENSION_MIME_TYPES: dict[str, frozenset[str]] = {
    "pdf": frozenset({PDF_MIME}),
    "docx": frozenset({DOCX_MIME}),
    "xlsx": frozenset({XLSX_MIME}),
    "pptx": frozenset({PPTX_MIME}),
    "txt": frozenset({PLAIN_TEXT_MIME}),
    "csv": frozenset({CSV_MIME, PLAIN_TEXT_MIME}),
    "png": frozenset({PNG_MIME}),
    "jpg": frozenset({JPEG_MIME}),
    "jpeg": frozenset({JPEG_MIME}),
}

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Zip entry name suffix that marks a VBA macro project, shared so macro
#: presence is only ever recognized one way.
MACRO_PROJECT_ENTRY_SUFFIX = "vbaproject.bin"


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    """Normalized ZIP-container facts used by multiple checks."""

    mime_type: str
    names: frozenset[str]
    entries: tuple[zipfile.ZipInfo, ...]
    corrupt: bool = False

    @property
    def has_macro_project(self) -> bool:
        """Whether any entry looks like a VBA macro project."""
        return any(name.endswith(MACRO_PROJECT_ENTRY_SUFFIX) for name in self.names)


def extension_of(filename: str) -> str:
    """Lowercase extension without the leading dot, or ``""`` if none."""
    return PurePath(filename).suffix.lower().removeprefix(".")


def inspect_archive(content: bytes) -> ArchiveInspection:
    """Inspect ZIP-container structure and recognize supported OOXML kinds.

    Presence of ``xl/workbook.xml`` (etc.) identifies the *container
    shape*, not full type safety — a macro-enabled workbook has the same
    entry, which is why :attr:`ArchiveInspection.has_macro_project` is a
    separate, explicit signal callers must check themselves when a macro
    payload must be rejected.
    """
    try:
        with zipfile.ZipFile(BytesIO(content), "r") as archive:
            entries = tuple(archive.infolist())
    except (OSError, ValueError, zipfile.BadZipFile):
        return ArchiveInspection(mime_type=ZIP_MIME, names=frozenset(), entries=(), corrupt=True)

    names = frozenset(entry.filename.lower() for entry in entries)
    if "word/document.xml" in names:
        mime_type = DOCX_MIME
    elif "xl/workbook.xml" in names:
        mime_type = XLSX_MIME
    elif "ppt/presentation.xml" in names:
        mime_type = PPTX_MIME
    else:
        mime_type = ZIP_MIME
    return ArchiveInspection(mime_type=mime_type, names=names, entries=entries)


def is_utf8_text(content: bytes) -> bool:
    """Conservative plain-text check: valid UTF-8, no NUL bytes.

    Deliberately simple and documented as the one text-detection rule
    both the Security Gate and upload quarantine rely on — no heuristics,
    no encoding guessing.
    """
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def detect_mime_type(
    content: bytes,
    extension: str,
    archive: ArchiveInspection | None,
) -> str:
    """Best-effort content type from magic bytes/container structure.

    ``archive`` must be the result of :func:`inspect_archive` when
    ``content`` starts with a ZIP signature, or ``None`` otherwise — the
    caller decides that once, so this function never re-parses the ZIP.
    """
    if content.startswith(b"%PDF-"):
        return PDF_MIME
    if archive is not None:
        return archive.mime_type
    if content.startswith(_OLE_SIGNATURE):
        return OLE_MIME
    if content.startswith(_PNG_SIGNATURE):
        return PNG_MIME
    if content.startswith(b"\xff\xd8\xff"):
        return JPEG_MIME
    if is_utf8_text(content):
        return CSV_MIME if extension == "csv" else PLAIN_TEXT_MIME
    return UNKNOWN_MIME
