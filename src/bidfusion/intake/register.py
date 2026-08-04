"""Register a local RFP package directory as bid documents (Domain A).

Intake assigns identity and exact content hashes. It performs no security
assessment: every registered document is untrusted until the Security Gate
has decided otherwise.

Reading is bounded and fails closed: files are opened without following
symlinks (where the platform supports ``O_NOFOLLOW``), the size limit is
checked on the open file descriptor *before* any content is read, content
is hashed chunk-wise under that limit, and a second ``fstat`` after the
read rejects files that changed underneath the reader (simple TOCTOU
races). A file that cannot be admitted is reported as ``RejectedFile`` —
never silently skipped — and a package with rejected files can never be
cleared by the package gate.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.document import Document
from bidfusion.schemas.ids import BidId, RunId
from bidfusion.security.preflight import EXTENSION_MIME_TYPES, UNKNOWN_MIME
from bidfusion.shared.identifiers import ArtifactIdAllocator, document_id_for
from bidfusion.shared.pathguards import is_repository_harness_path

_RAW_SCHEMA_VERSION = "1.0.0"
_CHUNK_SIZE = 1024 * 1024

DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024

# Patchable seam so tests can simulate a file changing between the two
# fstat calls without touching the global ``os`` module.
_fstat = os.fstat


@dataclass(frozen=True, slots=True)
class RejectedFile:
    """A package file that intake refused to admit (fail closed)."""

    filename: str
    reason: str


@dataclass(frozen=True, slots=True)
class RegisteredDocument:
    """One registered raw document plus its exact in-memory bytes."""

    document: Document
    content: bytes


@dataclass(frozen=True, slots=True)
class RegisteredPackage:
    """All registered documents of one local RFP package."""

    bid_id: BidId
    run_id: RunId
    package_name: str
    documents: tuple[RegisteredDocument, ...]
    rejected: tuple[RejectedFile, ...] = ()


def register_package(
    package_dir: Path,
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_ids: ArtifactIdAllocator,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> RegisteredPackage:
    """Register every admissible regular, non-hidden file below ``package_dir``.

    Files are ordered by their package-relative POSIX path, so repeated
    registration of the same package yields identical document identities.
    Hidden files are ignored; symlinks, non-regular files, oversized files,
    and files that change during reading are explicitly rejected.
    """
    if max_file_size_bytes < 1:
        msg = "the intake size limit must be positive"
        raise ValueError(msg)
    package_root = package_dir.resolve()
    if not package_root.is_dir():
        msg = f"package directory does not exist: {package_dir}"
        raise ValueError(msg)
    if is_repository_harness_path(package_root):
        msg = (
            "the repository inbox/ and results/ harness directories (and paths "
            "below them) must never be read by the pipeline"
        )
        raise ValueError(msg)

    registered: list[RegisteredDocument] = []
    rejected: list[RejectedFile] = []
    for path in _package_files(package_root):
        relative_name = path.relative_to(package_root).as_posix()
        if path.is_symlink():
            rejected.append(
                RejectedFile(
                    filename=relative_name,
                    reason="symbolic links are not processed (fail closed)",
                )
            )
            continue
        outcome = _read_bounded(path, max_file_size_bytes)
        if isinstance(outcome, str):
            rejected.append(RejectedFile(filename=relative_name, reason=outcome))
            continue

        content, content_digest = outcome
        extension = path.suffix.lower().removeprefix(".")
        expected_mime_types = EXTENSION_MIME_TYPES.get(extension)
        artifact = ArtifactReference(
            artifact_id=artifact_ids.allocate(),
            bid_id=bid_id,
            run_id=run_id,
            artifact_type=ArtifactType.RAW_DOCUMENT,
            schema_version=_RAW_SCHEMA_VERSION,
            content_ref=f"package/{relative_name}",
            content_hash=content_digest,
        )
        document = Document(
            document_id=document_id_for(len(registered) + 1),
            bid_id=bid_id,
            artifact=artifact,
            filename=relative_name,
            file_type=extension or "unknown",
            mime_type=min(expected_mime_types) if expected_mime_types else UNKNOWN_MIME,
            sha256=content_digest,
            size_bytes=len(content),
        )
        registered.append(RegisteredDocument(document=document, content=content))

    return RegisteredPackage(
        bid_id=bid_id,
        run_id=run_id,
        package_name=package_root.name,
        documents=tuple(registered),
        rejected=tuple(rejected),
    )


def _read_bounded(path: Path, limit: int) -> tuple[bytes, str] | str:
    """Read one regular file under the size limit; return a reason on refusal."""
    # O_NONBLOCK prevents blocking on FIFOs during open; it has no effect on
    # regular-file reads. Non-regular files are rejected right after fstat.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as failure:
        if failure.errno == errno.ELOOP:
            return "symbolic links are not processed (fail closed)"
        return "file could not be opened (fail closed)"

    try:
        before = _fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return "not a regular file (fail closed)"
        if before.st_size > limit:
            return f"file size {before.st_size} bytes exceeds the intake limit of {limit} bytes"

        hasher = sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                return "file grew beyond the intake limit during read (fail closed)"
            hasher.update(chunk)
            chunks.append(chunk)

        after = _fstat(descriptor)
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or total != before.st_size
        ):
            return "file changed while it was being read (fail closed)"
        return b"".join(chunks), hasher.hexdigest()
    except OSError:
        return "file could not be read (fail closed)"
    finally:
        os.close(descriptor)


def _package_files(package_root: Path) -> tuple[Path, ...]:
    # Everything except real directories is a candidate, so non-regular
    # entries (symlinks, FIFOs, sockets, ...) reach the explicit rejection
    # path instead of being silently filtered away.
    candidates = (
        path
        for path in package_root.rglob("*")
        if (path.is_symlink() or not path.is_dir())
        and not any(part.startswith(".") for part in path.relative_to(package_root).parts)
    )
    return tuple(sorted(candidates, key=lambda path: path.relative_to(package_root).as_posix()))
