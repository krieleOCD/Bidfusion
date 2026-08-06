"""Local upload quarantine service — no Flask, no network, no parser.

Validates a free-form upload against :class:`bidfusion.bidrun.policy.UploadPolicy`,
persists it below a controlled quarantine root, seals an
:class:`bidfusion.schemas.upload.UploadManifest`, and drives a fresh
``BidRun`` through ``CREATED -> UPLOADED -> QUARANTINED``
(:mod:`bidfusion.bidrun.transitions`). Nothing here ever calls
:func:`bidfusion.orchestration.run_package`, a parser, an extractor, or
the Security Gate — quarantine only ever produces untrusted, contained
bytes plus their audit trail (docs/architecture/level-1-target.md, §9).

Writes are staged, then atomically finalized: everything is written and
verified below a hidden staging directory first, and only a single
``os.rename`` (atomic on the same filesystem) below the same quarantine
root makes the package visible under its final name. A failure at any
point before that rename leaves no visible package at all.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY, UploadPolicy
from bidfusion.bidrun.transitions import apply_transition, create_bid_run
from bidfusion.orchestration import verify_run_integrity
from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.bidrun import AuthorizationRecord, BidRun, BidRunRecord, BidRunState
from bidfusion.schemas.ids import BidId, RunId
from bidfusion.schemas.upload import (
    DeletionStatus,
    QuarantinedUploadFile,
    RetentionPolicy,
    UploadManifest,
)
from bidfusion.shared.filetype import (
    ZIP_SIGNATURES,
    detect_mime_type,
    extension_of,
    inspect_archive,
)
from bidfusion.shared.identifiers import ArtifactIdAllocator, package_id_for
from bidfusion.shared.pathguards import is_inside_repository_checkout
from bidfusion.shared.payloads import (
    HASH_CONVENTION,
    artifact_payload_bytes,
    seal_artifact,
    verify_sealed_artifact,
)
from bidfusion.shared.secure_io import (
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    write_private_bytes,
)

_CHUNK_SIZE = 1024 * 1024
_MAX_DISPLAY_NAME_LENGTH = 255
_RAW_SCHEMA_VERSION = "1.0.0"
_MANIFEST_SCHEMA_VERSION = "1.0.0"
_MANIFEST_DOMAIN = "upload_manifest"
_MANIFEST_CONTENT_REF = "manifest/upload-manifest.payload.json"
_MANIFEST_AUDIT_REF = "manifest/upload-manifest.audit.json"
_BIDRUN_RECORD_SCHEMA_VERSION = "1.0.0"
_BIDRUN_RECORD_DOMAIN = "bid_run_record"
_BIDRUN_RECORD_CONTENT_REF = "bidrun/bidrun-record.payload.json"
_BIDRUN_RECORD_AUDIT_REF = "bidrun/bidrun-record.audit.json"
_INTEGRITY_MANIFEST_FILENAME = "integrity-manifest.json"
_FILES_DIRNAME = "files"
_STAGING_DIRNAME = ".staging"
_QUARANTINE_PRODUCER_NAME = "bidfusion-quarantine-service"
_QUARANTINE_PRODUCER_VERSION = "0.1.0"
_RETENTION_POLICY_VERSION = "0.1.0"


# --- errors -----------------------------------------------------------------

TOO_MANY_FILES = "TOO_MANY_FILES"
EMPTY_PACKAGE = "EMPTY_PACKAGE"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
PACKAGE_TOO_LARGE = "PACKAGE_TOO_LARGE"
INVALID_FILENAME = "INVALID_FILENAME"
DUPLICATE_DISPLAY_NAME = "DUPLICATE_DISPLAY_NAME"
EXTENSION_NOT_ALLOWED = "EXTENSION_NOT_ALLOWED"
TYPE_MISMATCH = "TYPE_MISMATCH"
MACRO_CONTENT_DETECTED = "MACRO_CONTENT_DETECTED"
EXISTING_PACKAGE = "EXISTING_PACKAGE"
QUARANTINE_ROOT_INVALID = "QUARANTINE_ROOT_INVALID"
AUTHORIZATION_NOT_ACCEPTED = "AUTHORIZATION_NOT_ACCEPTED"
STORAGE_ERROR = "STORAGE_ERROR"
INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
GENERIC_QUARANTINE_ERROR = "QUARANTINE_FAILURE"

#: Allowlist of known-safe error codes with their static operator-safe
#: messages. Never a raw filename, path, or library detail — see the
#: module docstring and ``bidfusion.document_understanding.canonical``
#: for the same pattern applied to parser failures.
_ERROR_MESSAGES: dict[str, str] = {
    TOO_MANY_FILES: "the package contains more files than the upload policy allows",
    EMPTY_PACKAGE: "the package contains no files",
    FILE_TOO_LARGE: "a file exceeds the upload policy's per-file size limit",
    PACKAGE_TOO_LARGE: "the package exceeds the upload policy's total size limit",
    INVALID_FILENAME: "an uploaded filename is not acceptable (fail closed)",
    DUPLICATE_DISPLAY_NAME: "two uploaded files normalize to the same display name",
    EXTENSION_NOT_ALLOWED: "an uploaded file's extension is not on the upload policy allowlist",
    TYPE_MISMATCH: "an uploaded file's content does not match its declared extension",
    MACRO_CONTENT_DETECTED: "an uploaded file contains macro content, which is never accepted",
    EXISTING_PACKAGE: "the target quarantine package already exists",
    QUARANTINE_ROOT_INVALID: "the configured quarantine root is not a valid location",
    AUTHORIZATION_NOT_ACCEPTED: "quarantine requires an already-accepted authorization",
    STORAGE_ERROR: "the upload could not be safely written to quarantine storage",
    INTEGRITY_FAILURE: "the persisted quarantine package failed its integrity check",
    GENERIC_QUARANTINE_ERROR: "the upload was rejected and no quarantine package was created",
}


class QuarantineError(RuntimeError):
    """An upload was rejected before any visible quarantine package existed.

    ``error_code`` is a stable, allowlisted identifier; the exception
    text is always the matching static operator-safe message — never a
    raw filename, absolute path, or library detail, even for failures
    raised deep inside filesystem helpers.
    """

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(_ERROR_MESSAGES.get(error_code, _ERROR_MESSAGES[GENERIC_QUARANTINE_ERROR]))


# --- input/output shapes ------------------------------------------------


class ReadableStream(Protocol):
    """Structural minimum of an uploaded file's byte stream.

    Deliberately not a Flask/Werkzeug type — this module has no web
    dependency. A later application-service layer adapts a real upload
    (e.g. ``werkzeug.datastructures.FileStorage.stream``) to this.
    """

    def read(self, size: int = ..., /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class UploadedFileInput:
    """One uploaded file as a bounded, readable stream.

    ``filename`` is the raw, browser-supplied name — untrusted and never
    used as a path; only :func:`quarantine_upload` derives a sanitized
    display name and an artifact-ID-based storage name from it.
    ``browser_content_type`` is the declared MIME type, if any — untrusted
    metadata only; type acceptance is always decided from actual bytes
    (:mod:`bidfusion.shared.filetype`), never from this field.
    """

    filename: str
    stream: ReadableStream
    browser_content_type: str | None = None


@dataclass(frozen=True, slots=True)
class QuarantineResult:
    """Outcome of one successful quarantine attempt.

    A plain return-value bundle, not a competing source of truth: the
    authoritative record is ``manifest`` (sealed, on disk). This mirrors
    :class:`bidfusion.orchestration.PipelineRunSummary`, which bundles a
    ``run_directory`` the same way.
    """

    bid_run: BidRun
    manifest: UploadManifest
    package_directory: Path


# --- filename handling --------------------------------------------------


def _sanitize_display_name(filename: str) -> str:
    """A safe, human-readable label — never a path, never trusted as one."""
    if not filename or "\x00" in filename:
        raise QuarantineError(INVALID_FILENAME)
    if "/" in filename or "\\" in filename:
        raise QuarantineError(INVALID_FILENAME)
    if filename.startswith(("/", "\\")) or ":" in filename:
        raise QuarantineError(INVALID_FILENAME)
    normalized = unicodedata.normalize("NFC", filename)
    if len(normalized) > _MAX_DISPLAY_NAME_LENGTH:
        raise QuarantineError(INVALID_FILENAME)
    stripped = normalized.strip()
    if not stripped or set(stripped) <= {"."}:
        raise QuarantineError(INVALID_FILENAME)
    for character in normalized:
        if unicodedata.category(character).startswith("C"):
            raise QuarantineError(INVALID_FILENAME)
    return normalized


# --- bounded reading and type detection ----------------------------------


def _read_bounded_stream(stream: ReadableStream, limit: int) -> bytes:
    """Read a stream in chunks, aborting as soon as it exceeds ``limit``.

    Never reads past the point where the limit is exceeded — the
    "bounded/chunked" guarantee the governing instructions require.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise QuarantineError(FILE_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _detect_and_validate_type(extension: str, content: bytes, policy: UploadPolicy) -> str:
    """Content-based type detection plus the upload policy's cross-check.

    Reuses :mod:`bidfusion.shared.filetype` — the same primitives the
    Security Gate's preflight uses — so there is exactly one magic-byte
    detection implementation. XLSX is technically ZIP-based; matching the
    ``xl/workbook.xml`` entry (not just any ZIP signature) is what keeps
    DOCX/PPTX/generic-ZIP from being misidentified as XLSX. A macro
    project entry is rejected explicitly even when the container
    otherwise looks like a plain XLSX workbook.
    """
    archive = inspect_archive(content) if content.startswith(ZIP_SIGNATURES) else None
    detected_mime = detect_mime_type(content, extension, archive)
    expected_mime_types = policy.allowed_mime_types_by_extension.get(extension, frozenset())
    if detected_mime not in expected_mime_types:
        raise QuarantineError(TYPE_MISMATCH)
    if archive is not None and archive.has_macro_project:
        raise QuarantineError(MACRO_CONTENT_DETECTED)
    return detected_mime


# --- staged, digest-tracked writing --------------------------------------


class _StagingWriter:
    """Write confidential quarantine files below one staging directory,
    tracking whole-file digests for the final integrity manifest — the
    quarantine counterpart of the pipeline's own run writer
    (``bidfusion.orchestration.local_pipeline._RunWriter``)."""

    def __init__(self, staging_dir: Path, *, root: Path) -> None:
        self._staging_dir = staging_dir
        self._root = root
        self._digests: dict[str, str] = {}

    def write_bytes(self, relative: str, data: bytes) -> str:
        write_private_bytes(self._staging_dir / relative, data, root=self._root)
        digest = sha256(data).hexdigest()
        self._digests[relative] = digest
        return digest

    def write_json(self, relative: str, payload: dict[str, object]) -> None:
        self.write_bytes(relative, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def write_integrity_manifest(self) -> None:
        manifest = {
            "hash_convention": HASH_CONVENTION,
            "files": dict(sorted(self._digests.items())),
        }
        write_private_bytes(
            self._staging_dir / _INTEGRITY_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            root=self._root,
        )


def _verify_modes(staging_dir: Path) -> None:
    """Re-verify every written path is owner-only and not a symlink."""
    info = staging_dir.lstat()
    if stat.S_ISLNK(info.st_mode) or stat.S_IMODE(info.st_mode) != PRIVATE_DIR_MODE:
        raise QuarantineError(STORAGE_ERROR)
    for path in staging_dir.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise QuarantineError(STORAGE_ERROR)
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != PRIVATE_DIR_MODE:
                raise QuarantineError(STORAGE_ERROR)
        elif stat.S_ISREG(info.st_mode):
            if stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE:
                raise QuarantineError(STORAGE_ERROR)
        else:
            raise QuarantineError(STORAGE_ERROR)


def _verify_owned_by_current_user(path: Path) -> None:
    """Fail closed if ``path`` is not owned by this process's effective user.

    Quarantine-specific hardening (M1): only applied to the quarantine
    root and package/staging directories here, never to
    :mod:`bidfusion.shared.secure_io`'s general-purpose helpers, which
    the existing pipeline also relies on. A pre-existing, 0700,
    non-symlink directory that happens to be owned by someone else could
    otherwise be reused to plant or read quarantine contents outside this
    process's control.

    Silently skipped wherever the platform exposes neither
    ``os.geteuid`` nor ``st_uid`` (e.g. Windows) — the 0700/symlink
    checks already applied everywhere still stand on their own there.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return
    info = path.lstat()
    owner_id = getattr(info, "st_uid", None)
    if owner_id is None:
        return
    if owner_id != geteuid():
        raise QuarantineError(QUARANTINE_ROOT_INVALID)


# --- the service ----------------------------------------------------------


def quarantine_upload(
    *,
    bid_id: BidId,
    run_id: RunId,
    authorization: AuthorizationRecord,
    files: Sequence[UploadedFileInput],
    quarantine_root: Path,
    now: datetime,
    policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
) -> QuarantineResult:
    """Validate, quarantine, and manifest one upload; drive its BidRun.

    Never calls :func:`bidfusion.orchestration.run_package`, a parser, an
    extractor, or the Security Gate. On any rejection, no visible
    quarantine package is left behind and no ``BidRun`` is returned.
    """
    if not authorization.accepted:
        raise QuarantineError(AUTHORIZATION_NOT_ACCEPTED)

    run = create_bid_run(bid_id=bid_id, run_id=run_id, authorization=authorization, created_at=now)
    run = apply_transition(run, to=BidRunState.UPLOADED, occurred_at=now)

    # ``resolve()`` transparently follows symlinks, so a symlinked root
    # must be rejected *before* resolving it — otherwise this check would
    # silently accept whatever the symlink points to.
    if quarantine_root.is_symlink():
        raise QuarantineError(QUARANTINE_ROOT_INVALID)
    resolved_root = quarantine_root.resolve()
    if is_inside_repository_checkout(resolved_root):
        raise QuarantineError(QUARANTINE_ROOT_INVALID)

    staging_dir: Path | None = None
    try:
        try:
            ensure_private_directory(resolved_root)
            _verify_owned_by_current_user(resolved_root)
        except (OSError, ValueError) as failure:
            raise QuarantineError(QUARANTINE_ROOT_INVALID) from failure

        if not files:
            raise QuarantineError(EMPTY_PACKAGE)
        if len(files) > policy.max_files_per_package:
            raise QuarantineError(TOO_MANY_FILES)

        package_id = package_id_for(now)
        staging_dir = resolved_root / _STAGING_DIRNAME / package_id
        final_dir = resolved_root / package_id
        if os.path.lexists(final_dir):
            raise QuarantineError(EXISTING_PACKAGE)

        ensure_private_directory(staging_dir, root=resolved_root)
        _verify_owned_by_current_user(staging_dir)
        writer = _StagingWriter(staging_dir, root=resolved_root)
        artifact_ids = ArtifactIdAllocator(now)

        display_names: set[str] = set()
        quarantined_files: list[QuarantinedUploadFile] = []
        total_size = 0
        for upload in files:
            display_name = _sanitize_display_name(upload.filename)
            if display_name in display_names:
                raise QuarantineError(DUPLICATE_DISPLAY_NAME)
            display_names.add(display_name)

            extension = extension_of(display_name)
            if extension not in policy.allowed_extensions:
                raise QuarantineError(EXTENSION_NOT_ALLOWED)

            content = _read_bounded_stream(upload.stream, policy.max_file_size_bytes)
            total_size += len(content)
            if total_size > policy.max_package_size_bytes:
                raise QuarantineError(PACKAGE_TOO_LARGE)

            detected_mime = _detect_and_validate_type(extension, content, policy)

            file_artifact_id = artifact_ids.allocate()
            content_ref = f"{_FILES_DIRNAME}/{file_artifact_id}.{extension}"
            digest = writer.write_bytes(content_ref, content)
            artifact = ArtifactReference(
                artifact_id=file_artifact_id,
                bid_id=bid_id,
                run_id=run_id,
                artifact_type=ArtifactType.RAW_DOCUMENT,
                schema_version=_RAW_SCHEMA_VERSION,
                content_ref=content_ref,
                content_hash=digest,
            )
            quarantined_files.append(
                QuarantinedUploadFile(
                    artifact=artifact,
                    display_name=display_name,
                    detected_type=detected_mime,
                    extension=extension,
                    size_bytes=len(content),
                    sha256=digest,
                )
            )

        manifest = seal_artifact(
            lambda envelope: UploadManifest(
                artifact=envelope,
                package_id=package_id,
                bid_id=bid_id,
                run_id=run_id,
                authorization=authorization,
                policy_name=policy.policy_name,
                policy_version=policy.policy_version,
                files=tuple(quarantined_files),
                total_size_bytes=total_size,
                created_at=now,
                retention_policy=RetentionPolicy.MANUAL_DELETION_REQUIRED,
                retention_policy_version=_RETENTION_POLICY_VERSION,
                expires_at=None,
                deletion_status=DeletionStatus.ACTIVE,
                deletion_requested_at=None,
                deleted_at=None,
            ),
            artifact_id=artifact_ids.allocate(),
            bid_id=bid_id,
            run_id=run_id,
            artifact_type=ArtifactType.UPLOAD_MANIFEST,
            schema_version=_MANIFEST_SCHEMA_VERSION,
            domain=_MANIFEST_DOMAIN,
            content_ref=_MANIFEST_CONTENT_REF,
            producer_component=_QUARANTINE_PRODUCER_NAME,
            producer_version=_QUARANTINE_PRODUCER_VERSION,
            input_artifacts=tuple(file.artifact for file in quarantined_files),
            created_at=now,
        )

        writer.write_bytes(
            _MANIFEST_CONTENT_REF, artifact_payload_bytes(manifest, domain=_MANIFEST_DOMAIN)
        )
        writer.write_json(_MANIFEST_AUDIT_REF, manifest.model_dump(mode="json"))

        manifest_reference = manifest.artifact.as_reference()
        run = apply_transition(
            run,
            to=BidRunState.QUARANTINED,
            occurred_at=now,
            artifact_refs=(manifest_reference, *(file.artifact for file in quarantined_files)),
            source_package_artifact=manifest_reference,
        )

        record = seal_artifact(
            lambda envelope: BidRunRecord(artifact=envelope, bid_run=run),
            artifact_id=artifact_ids.allocate(),
            bid_id=bid_id,
            run_id=run_id,
            artifact_type=ArtifactType.BID_RUN_RECORD,
            schema_version=_BIDRUN_RECORD_SCHEMA_VERSION,
            domain=_BIDRUN_RECORD_DOMAIN,
            content_ref=_BIDRUN_RECORD_CONTENT_REF,
            producer_component=_QUARANTINE_PRODUCER_NAME,
            producer_version=_QUARANTINE_PRODUCER_VERSION,
            input_artifacts=run.artifact_refs,
            created_at=now,
        )
        writer.write_bytes(
            _BIDRUN_RECORD_CONTENT_REF, artifact_payload_bytes(record, domain=_BIDRUN_RECORD_DOMAIN)
        )
        writer.write_json(_BIDRUN_RECORD_AUDIT_REF, record.model_dump(mode="json"))
        writer.write_integrity_manifest()

        if verify_run_integrity(staging_dir):
            raise QuarantineError(STORAGE_ERROR)
        _verify_modes(staging_dir)

        if os.path.lexists(final_dir):
            raise QuarantineError(EXISTING_PACKAGE)
        os.rename(staging_dir, final_dir)
        staging_dir = None  # finalized: nothing left to clean up

        if not final_dir.resolve().is_relative_to(resolved_root):
            raise QuarantineError(STORAGE_ERROR)

        return QuarantineResult(bid_run=run, manifest=manifest, package_directory=final_dir)
    except QuarantineError:
        raise
    except (OSError, ValueError):
        raise QuarantineError(STORAGE_ERROR) from None
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _read_sealed_authoritative[ModelT: BaseModel](
    package_directory: Path,
    *,
    content_ref: str,
    audit_ref: str,
    model_type: type[ModelT],
    domain: str,
) -> ModelT:
    """Reconstruct one sealed artifact with the payload file as the sole
    source of content.

    Repository convention (``shared/payloads.py``): the payload file is
    the authoritative representation; the audit file is a derived
    convenience copy that "must never be processed independently as a
    valid artifact." Accordingly:

    - every *content* field of the returned model comes exclusively from
      ``content_ref`` (the ``.payload.json`` file) — the audit file's own
      copy of those fields, if any, is never read;
    - the audit file supplies only the administrative envelope shell
      (``artifact_id``, ``producer``, ``input_artifacts``, the envelope
      timestamp, and the *claimed* ``content_hash``) needed to assemble a
      complete model instance, since the payload file deliberately
      excludes the envelope (it would be self-referential otherwise);
    - that claimed ``content_hash`` is never trusted on its own —
      :func:`bidfusion.shared.payloads.verify_sealed_artifact` independently
      recomputes it from the reconstructed model's own (payload-sourced)
      content and rejects any mismatch.

    A forged or stale audit file therefore can never change what is
    returned (only cause a safe rejection if it disagrees with the real
    payload), and a missing or malformed audit file fails closed the
    same way as a missing or malformed payload file — there is no
    behavior in which audit-file content reaches the caller.
    """
    payload_document = json.loads((package_directory / content_ref).read_text(encoding="utf-8"))
    if not isinstance(payload_document, dict):
        raise QuarantineError(INTEGRITY_FAILURE)
    content_fields = payload_document.get("payload")
    if not isinstance(content_fields, dict):
        raise QuarantineError(INTEGRITY_FAILURE)

    audit_document = json.loads((package_directory / audit_ref).read_text(encoding="utf-8"))
    if not isinstance(audit_document, dict):
        raise QuarantineError(INTEGRITY_FAILURE)
    envelope_fields = audit_document.get("artifact")
    if not isinstance(envelope_fields, dict):
        raise QuarantineError(INTEGRITY_FAILURE)
    # Forward-safety note: verify_sealed_artifact() below only proves that
    # the *content_hash* claimed here matches the payload-sourced content.
    # It says nothing about the rest of this envelope shell — producer,
    # the envelope's own created_at, and (for BidRunRecord) the envelope
    # artifact_id are administrative metadata taken from the audit file
    # as-is and are not currently used as trusted domain or display data
    # anywhere in this codebase. Future consumers must not start treating
    # them as verified business facts without extending the sealing model
    # to cover them (e.g. hashing them, or sourcing them from elsewhere).

    model = model_type.model_validate({**content_fields, "artifact": envelope_fields})
    try:
        # UploadManifest and BidRunRecord both structurally satisfy
        # EnvelopedArtifact (an `artifact: ArtifactEnvelope` field plus
        # pydantic's model_dump); the generic bound here is BaseModel
        # (for .model_validate), so mypy cannot see that on its own.
        verify_sealed_artifact(model, domain=domain)  # type: ignore[arg-type]
    except ValueError:
        raise QuarantineError(INTEGRITY_FAILURE) from None
    return model


def read_quarantine_package(package_directory: Path) -> QuarantineResult:
    """Re-read and re-verify one quarantine package from disk.

    This is the framework-free "quarantine service boundary" for the
    *read* side: it never trusts a session-local UI registry, and it
    never trusts the derived audit JSON either — every returned field
    is sourced from the authoritative sealed payload files and checked
    with :func:`bidfusion.shared.payloads.verify_sealed_artifact` (see
    :func:`_read_sealed_authoritative`). Any digest mismatch, schema
    violation, or lineage inconsistency collapses to one safe
    :class:`QuarantineError` (``INTEGRITY_FAILURE``) — never a raw file
    path, JSON fragment, or validation-error detail.
    """
    try:
        if verify_run_integrity(package_directory):
            raise QuarantineError(INTEGRITY_FAILURE)
        manifest = _read_sealed_authoritative(
            package_directory,
            content_ref=_MANIFEST_CONTENT_REF,
            audit_ref=_MANIFEST_AUDIT_REF,
            model_type=UploadManifest,
            domain=_MANIFEST_DOMAIN,
        )
        record = _read_sealed_authoritative(
            package_directory,
            content_ref=_BIDRUN_RECORD_CONTENT_REF,
            audit_ref=_BIDRUN_RECORD_AUDIT_REF,
            model_type=BidRunRecord,
            domain=_BIDRUN_RECORD_DOMAIN,
        )
    except QuarantineError:
        raise
    except (OSError, ValueError):
        raise QuarantineError(INTEGRITY_FAILURE) from None

    manifest_reference = manifest.artifact.as_reference()
    expected_lineage = {manifest_reference.artifact_id: manifest_reference}
    expected_lineage.update({file.artifact.artifact_id: file.artifact for file in manifest.files})
    run_lineage = {item.artifact_id: item for item in record.bid_run.artifact_refs}
    lineage_matches = run_lineage == expected_lineage
    identity_matches = (
        record.bid_run.bid_id == manifest.bid_id
        and record.bid_run.run_id == manifest.run_id
        and record.bid_run.source_package_artifact == manifest_reference
    )
    if not identity_matches or not lineage_matches:
        raise QuarantineError(INTEGRITY_FAILURE)

    return QuarantineResult(
        bid_run=record.bid_run, manifest=manifest, package_directory=package_directory
    )
