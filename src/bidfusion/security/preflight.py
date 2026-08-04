"""Deterministic, provider-free assessment of untrusted raw document bytes."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import PurePath

from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import Severity
from bidfusion.schemas.ids import DocumentId
from bidfusion.schemas.security import (
    PreflightAssessment,
    SecurityCheckResult,
    SecurityCheckStatus,
)

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
DEFAULT_ALLOWED_MIME_TYPES = frozenset(
    {
        PDF_MIME,
        DOCX_MIME,
        XLSX_MIME,
        PPTX_MIME,
        PLAIN_TEXT_MIME,
        CSV_MIME,
        PNG_MIME,
        JPEG_MIME,
    }
)
DEFAULT_BLOCKED_EXTENSIONS = frozenset(
    {"exe", "dll", "bat", "cmd", "ps1", "sh", "js", "vbs", "scr", "com", "msi"}
)
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

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PDF_JAVASCRIPT = re.compile(rb"/(?:JS|JavaScript)\b")


class PreflightInputError(ValueError):
    """The scanner was not given a coherent raw-artifact input."""


class ArtifactContentMismatchError(PreflightInputError):
    """The supplied bytes do not match the immutable artifact reference."""


@dataclass(frozen=True, slots=True)
class PreflightConfig:
    """Operational limits for deterministic inspection, not gate-decision policy."""

    max_file_size_bytes: int = 100 * 1024 * 1024
    allowed_mime_types: frozenset[str] = DEFAULT_ALLOWED_MIME_TYPES
    blocked_extensions: frozenset[str] = DEFAULT_BLOCKED_EXTENSIONS
    max_archive_entries: int = 10_000
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    max_archive_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        numeric_limits = (
            self.max_file_size_bytes,
            self.max_archive_entries,
            self.max_archive_uncompressed_bytes,
        )
        if any(limit <= 0 for limit in numeric_limits):
            msg = "preflight size and entry limits must be positive"
            raise ValueError(msg)
        if self.max_archive_compression_ratio <= 1.0:
            msg = "archive compression-ratio limit must be greater than one"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _ArchiveInspection:
    """Normalized ZIP-container facts used by multiple checks."""

    mime_type: str
    names: frozenset[str]
    entries: tuple[zipfile.ZipInfo, ...]
    corrupt: bool = False


class DeterministicPreflightScanner:
    """Assess raw bytes without filesystem, network, OCR, or provider access."""

    def __init__(
        self,
        *,
        config: PreflightConfig | None = None,
        scanner_name: str = "bidfusion-deterministic-preflight",
        scanner_version: str = "1.0.0",
    ) -> None:
        if not scanner_name.strip() or not scanner_version.strip():
            msg = "scanner name and version must be non-empty"
            raise ValueError(msg)
        self._config = config or PreflightConfig()
        self._scanner_name = scanner_name
        self._scanner_version = scanner_version

    def assess(
        self,
        *,
        artifact: ArtifactReference,
        document_id: DocumentId,
        filename: str,
        content: bytes,
        assessed_at: datetime | None = None,
    ) -> PreflightAssessment:
        """Run every deterministic check and bind observations to exact bytes."""
        if artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "deterministic preflight accepts only raw_document artifacts"
            raise PreflightInputError(msg)

        observed_hash = sha256(content).hexdigest()
        if observed_hash != artifact.content_hash:
            msg = "supplied content does not match the artifact content hash"
            raise ArtifactContentMismatchError(msg)

        extension = _extension(filename)
        archive = _inspect_archive(content) if content.startswith(_ZIP_SIGNATURES) else None
        detected_mime = _detect_mime(content, extension, archive)

        checks = (
            SecurityCheckResult(
                check="content_hash",
                status=SecurityCheckStatus.PASS,
                message="Supplied bytes match the immutable artifact content hash.",
                details={"sha256": observed_hash},
            ),
            self._guard(
                "file_size",
                lambda: self._check_file_size(len(content)),
            ),
            self._guard(
                "mime_type",
                lambda: self._check_mime_type(detected_mime),
            ),
            self._guard(
                "extension_mime",
                lambda: self._check_extension_mime(extension, detected_mime),
            ),
            self._guard(
                "structural_integrity",
                lambda: _check_structural_integrity(content, detected_mime, archive),
            ),
            self._guard(
                "archive_limits",
                lambda: self._check_archive_limits(archive),
            ),
            self._guard(
                "macro_detection",
                lambda: _check_macros(detected_mime, archive),
            ),
            self._guard(
                "embedded_objects",
                lambda: _check_embedded_objects(detected_mime, archive),
            ),
            self._guard(
                "pdf_javascript",
                lambda: _check_pdf_javascript(content, detected_mime),
            ),
            self._guard(
                "pdf_embedded_files",
                lambda: _check_pdf_embedded_files(content, detected_mime),
            ),
            self._guard(
                "encryption",
                lambda: _check_encryption(content, detected_mime, archive),
            ),
        )

        return PreflightAssessment(
            bid_id=artifact.bid_id,
            document_id=document_id,
            artifact=artifact,
            content_hash=observed_hash,
            scanner=self._scanner_name,
            scanner_version=self._scanner_version,
            assessed_at=assessed_at or datetime.now(UTC),
            checks=checks,
        )

    def _guard(
        self,
        check_name: str,
        operation: Callable[[], SecurityCheckResult],
    ) -> SecurityCheckResult:
        try:
            return operation()
        except Exception:
            return SecurityCheckResult(
                check=check_name,
                status=SecurityCheckStatus.ERROR,
                message="The deterministic check did not complete.",
            )

    def _check_file_size(self, size_bytes: int) -> SecurityCheckResult:
        details = {
            "size_bytes": str(size_bytes),
            "max_size_bytes": str(self._config.max_file_size_bytes),
        }
        if size_bytes > self._config.max_file_size_bytes:
            return SecurityCheckResult(
                check="file_size",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.CRITICAL,
                message="Document exceeds the configured preflight size limit.",
                details=details,
            )
        return SecurityCheckResult(
            check="file_size",
            status=SecurityCheckStatus.PASS,
            message="Document is within the configured preflight size limit.",
            details=details,
        )

    def _check_mime_type(self, detected_mime: str) -> SecurityCheckResult:
        if detected_mime not in self._config.allowed_mime_types:
            return SecurityCheckResult(
                check="mime_type",
                status=SecurityCheckStatus.UNKNOWN,
                message="Detected content type is not in the preflight allowlist.",
                details={"detected_mime": detected_mime},
            )
        return SecurityCheckResult(
            check="mime_type",
            status=SecurityCheckStatus.PASS,
            message="Detected content type is in the preflight allowlist.",
            details={"detected_mime": detected_mime},
        )

    def _check_extension_mime(
        self,
        extension: str,
        detected_mime: str,
    ) -> SecurityCheckResult:
        if extension in self._config.blocked_extensions:
            return SecurityCheckResult(
                check="extension_mime",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.CRITICAL,
                message="Filename uses an explicitly blocked extension.",
                details={"extension": extension, "detected_mime": detected_mime},
            )

        expected_mime_types = EXTENSION_MIME_TYPES.get(extension)
        if expected_mime_types is None:
            return SecurityCheckResult(
                check="extension_mime",
                status=SecurityCheckStatus.UNKNOWN,
                message="Filename extension is missing or unsupported.",
                details={"extension": extension or "<none>", "detected_mime": detected_mime},
            )
        if detected_mime not in expected_mime_types:
            return SecurityCheckResult(
                check="extension_mime",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="Filename extension does not match the detected content type.",
                details={
                    "extension": extension,
                    "detected_mime": detected_mime,
                    "expected_mime": ",".join(sorted(expected_mime_types)),
                },
            )
        return SecurityCheckResult(
            check="extension_mime",
            status=SecurityCheckStatus.PASS,
            message="Filename extension matches the detected content type.",
            details={"extension": extension, "detected_mime": detected_mime},
        )

    def _check_archive_limits(
        self,
        archive: _ArchiveInspection | None,
    ) -> SecurityCheckResult:
        if archive is None:
            return _not_applicable("archive_limits", "Document is not a ZIP container.")
        if archive.corrupt:
            return SecurityCheckResult(
                check="archive_limits",
                status=SecurityCheckStatus.ERROR,
                message="Archive limits could not be assessed because the ZIP is corrupt.",
            )

        entry_count = len(archive.entries)
        uncompressed_bytes = sum(entry.file_size for entry in archive.entries)
        compressed_bytes = sum(entry.compress_size for entry in archive.entries)
        compression_ratio = uncompressed_bytes / max(compressed_bytes, 1)
        details = {
            "entry_count": str(entry_count),
            "uncompressed_bytes": str(uncompressed_bytes),
            "compressed_bytes": str(compressed_bytes),
            "compression_ratio": f"{compression_ratio:.2f}",
        }

        exceeded = (
            entry_count > self._config.max_archive_entries
            or uncompressed_bytes > self._config.max_archive_uncompressed_bytes
            or compression_ratio > self._config.max_archive_compression_ratio
        )
        if exceeded:
            return SecurityCheckResult(
                check="archive_limits",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="Archive expansion properties exceed configured safety limits.",
                details=details,
            )
        return SecurityCheckResult(
            check="archive_limits",
            status=SecurityCheckStatus.PASS,
            message="Archive expansion properties are within configured safety limits.",
            details=details,
        )


def _extension(filename: str) -> str:
    return PurePath(filename).suffix.lower().removeprefix(".")


def _inspect_archive(content: bytes) -> _ArchiveInspection:
    try:
        with zipfile.ZipFile(BytesIO(content), "r") as archive:
            entries = tuple(archive.infolist())
    except (OSError, ValueError, zipfile.BadZipFile):
        return _ArchiveInspection(
            mime_type=ZIP_MIME,
            names=frozenset(),
            entries=(),
            corrupt=True,
        )

    names = frozenset(entry.filename.lower() for entry in entries)
    if "word/document.xml" in names:
        mime_type = DOCX_MIME
    elif "xl/workbook.xml" in names:
        mime_type = XLSX_MIME
    elif "ppt/presentation.xml" in names:
        mime_type = PPTX_MIME
    else:
        mime_type = ZIP_MIME
    return _ArchiveInspection(mime_type=mime_type, names=names, entries=entries)


def _detect_mime(
    content: bytes,
    extension: str,
    archive: _ArchiveInspection | None,
) -> str:
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
    if _is_utf8_text(content):
        return CSV_MIME if extension == "csv" else PLAIN_TEXT_MIME
    return UNKNOWN_MIME


def _is_utf8_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _check_structural_integrity(
    content: bytes,
    detected_mime: str,
    archive: _ArchiveInspection | None,
) -> SecurityCheckResult:
    if detected_mime == PDF_MIME:
        if b"%%EOF" not in content[-2048:]:
            return SecurityCheckResult(
                check="structural_integrity",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="PDF does not contain an end-of-file marker near its end.",
            )
        return _passed("structural_integrity", "PDF has the expected boundary markers.")

    if detected_mime in OFFICE_MIME_TYPES:
        if archive is None or archive.corrupt:
            return SecurityCheckResult(
                check="structural_integrity",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="Office document ZIP structure is corrupt.",
            )
        return _passed(
            "structural_integrity",
            "Office document contains the expected OOXML structure.",
        )

    if detected_mime == ZIP_MIME:
        if archive is not None and archive.corrupt:
            return SecurityCheckResult(
                check="structural_integrity",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="ZIP central directory is corrupt.",
            )
        return SecurityCheckResult(
            check="structural_integrity",
            status=SecurityCheckStatus.UNKNOWN,
            message="ZIP container is not a recognized supported Office document.",
        )

    if detected_mime == PNG_MIME:
        if not content.endswith(b"IEND\xaeB`\x82"):
            return SecurityCheckResult(
                check="structural_integrity",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="PNG does not contain the expected end marker.",
            )
        return _passed("structural_integrity", "PNG has the expected boundary markers.")

    if detected_mime == JPEG_MIME:
        if not content.endswith(b"\xff\xd9"):
            return SecurityCheckResult(
                check="structural_integrity",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="JPEG does not contain the expected end marker.",
            )
        return _passed("structural_integrity", "JPEG has the expected boundary markers.")

    if detected_mime in (PLAIN_TEXT_MIME, CSV_MIME):
        return _passed("structural_integrity", "Text content is valid UTF-8 without NUL bytes.")

    return SecurityCheckResult(
        check="structural_integrity",
        status=SecurityCheckStatus.UNKNOWN,
        message="Structural integrity cannot be determined for the detected content type.",
        details={"detected_mime": detected_mime},
    )


def _check_macros(
    detected_mime: str,
    archive: _ArchiveInspection | None,
) -> SecurityCheckResult:
    if detected_mime not in OFFICE_MIME_TYPES:
        return _not_applicable("macro_detection", "Document is not a supported Office format.")
    if archive is None or archive.corrupt:
        return SecurityCheckResult(
            check="macro_detection",
            status=SecurityCheckStatus.ERROR,
            message="Macro inspection could not read the Office ZIP structure.",
        )

    macro_paths = sorted(name for name in archive.names if name.endswith("vbaproject.bin"))
    if macro_paths:
        return SecurityCheckResult(
            check="macro_detection",
            status=SecurityCheckStatus.FAIL,
            severity=Severity.CRITICAL,
            message="Office document contains a VBA macro project.",
            details={"entries": ",".join(macro_paths)},
        )
    return _passed("macro_detection", "No VBA macro project was found.")


def _check_embedded_objects(
    detected_mime: str,
    archive: _ArchiveInspection | None,
) -> SecurityCheckResult:
    if detected_mime not in OFFICE_MIME_TYPES:
        return _not_applicable(
            "embedded_objects",
            "Document is not a supported Office format.",
        )
    if archive is None or archive.corrupt:
        return SecurityCheckResult(
            check="embedded_objects",
            status=SecurityCheckStatus.ERROR,
            message="Embedded-object inspection could not read the Office ZIP structure.",
        )

    object_paths = sorted(
        name for name in archive.names if "/embeddings/" in f"/{name}" or "oleobject" in name
    )
    if object_paths:
        return SecurityCheckResult(
            check="embedded_objects",
            status=SecurityCheckStatus.FAIL,
            severity=Severity.HIGH,
            message="Office document contains embedded object content.",
            details={"entries": ",".join(object_paths)},
        )
    return _passed("embedded_objects", "No embedded Office objects were found.")


def _check_pdf_javascript(content: bytes, detected_mime: str) -> SecurityCheckResult:
    if detected_mime != PDF_MIME:
        return _not_applicable("pdf_javascript", "Document is not a PDF.")
    indicators = sorted(
        {match.group(0).decode("ascii") for match in _PDF_JAVASCRIPT.finditer(content)}
    )
    if indicators:
        return SecurityCheckResult(
            check="pdf_javascript",
            status=SecurityCheckStatus.FAIL,
            severity=Severity.HIGH,
            message="PDF contains JavaScript dictionary indicators.",
            details={"indicators": ",".join(indicators)},
        )
    return _passed("pdf_javascript", "No PDF JavaScript indicators were found.")


def _check_pdf_embedded_files(content: bytes, detected_mime: str) -> SecurityCheckResult:
    if detected_mime != PDF_MIME:
        return _not_applicable("pdf_embedded_files", "Document is not a PDF.")
    if b"/EmbeddedFile" in content:
        return SecurityCheckResult(
            check="pdf_embedded_files",
            status=SecurityCheckStatus.FAIL,
            severity=Severity.HIGH,
            message="PDF contains an embedded-file object.",
            details={"indicator": "/EmbeddedFile"},
        )
    return _passed("pdf_embedded_files", "No PDF embedded-file object was found.")


def _check_encryption(
    content: bytes,
    detected_mime: str,
    archive: _ArchiveInspection | None,
) -> SecurityCheckResult:
    if detected_mime == PDF_MIME:
        if b"/Encrypt" in content:
            return SecurityCheckResult(
                check="encryption",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="PDF declares an encryption dictionary.",
            )
        return _passed("encryption", "PDF does not declare an encryption dictionary.")

    if detected_mime in OFFICE_MIME_TYPES:
        if archive is None or archive.corrupt:
            return SecurityCheckResult(
                check="encryption",
                status=SecurityCheckStatus.ERROR,
                message="Encryption inspection could not read the Office ZIP structure.",
            )
        if any(entry.flag_bits & 0x1 for entry in archive.entries):
            return SecurityCheckResult(
                check="encryption",
                status=SecurityCheckStatus.FAIL,
                severity=Severity.HIGH,
                message="Office ZIP contains encrypted entries.",
            )
        return _passed("encryption", "Office ZIP entries are not encrypted.")

    return _not_applicable(
        "encryption",
        "No deterministic encryption check applies to this content type.",
    )


def _passed(check: str, message: str) -> SecurityCheckResult:
    return SecurityCheckResult(
        check=check,
        status=SecurityCheckStatus.PASS,
        message=message,
    )


def _not_applicable(check: str, message: str) -> SecurityCheckResult:
    return SecurityCheckResult(
        check=check,
        status=SecurityCheckStatus.NOT_APPLICABLE,
        message=message,
    )
