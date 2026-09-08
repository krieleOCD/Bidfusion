"""View models for the free-upload flow: pure projections of the
persisted, re-verified quarantine truth into display structures.

Nothing here decides quarantine outcomes — this module only reads back
what :func:`bidfusion.bidrun.quarantine.read_quarantine_package` already
verified and picks which fields are safe to render. Absolute paths,
internal artifact-ID-based filenames, full content refs, and full
hashes are deliberately never included in any view model here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY, UploadPolicy
from bidfusion.bidrun.quarantine import read_quarantine_package
from bidfusion.local_ui.viewmodels import StatusDisplay

_DISPLAY_EXTENSION_ORDER = ("pdf", "xlsx", "txt")
_STATIC_AUTHORIZATION_STATUS = "Confirmed for non-production testing"
_STATIC_QUARANTINE_MESSAGE = (
    "Uploaded and quarantined. No parsing or security clearance has occurred."
)
_SHORT_HASH_LENGTH = 12


@dataclass(frozen=True, slots=True)
class UploadPolicyView:
    """Formatted, template-ready projection of the upload acceptance policy."""

    allowed_extensions: str
    max_files_per_package: int
    max_file_size_label: str
    max_package_size_label: str


def upload_policy_view(policy: UploadPolicy = DEFAULT_UPLOAD_POLICY) -> UploadPolicyView:
    ordered = [
        extension
        for extension in _DISPLAY_EXTENSION_ORDER
        if extension in policy.allowed_extensions
    ]
    ordered.extend(sorted(policy.allowed_extensions - set(_DISPLAY_EXTENSION_ORDER)))
    return UploadPolicyView(
        allowed_extensions=", ".join(extension.upper() for extension in ordered),
        max_files_per_package=policy.max_files_per_package,
        max_file_size_label=_format_size(policy.max_file_size_bytes),
        max_package_size_label=_format_size(policy.max_package_size_bytes),
    )


@dataclass(frozen=True, slots=True)
class UploadFileRow:
    """One quarantined file, projected for display only."""

    display_name: str
    detected_type: str
    size_label: str
    short_hash: str


@dataclass(frozen=True, slots=True)
class UploadResultView:
    """Display projection of one quarantined upload — never a success state."""

    key: str
    status: StatusDisplay
    status_message: str
    files: tuple[UploadFileRow, ...]
    file_count: int
    policy_name: str
    policy_version: str
    retention_policy: str
    deletion_status: str
    authorization_status: str
    created_at: str


def build_upload_result_view(key: str, package_directory: Path) -> UploadResultView:
    """Re-read and re-verify the persisted package, then project it.

    Raises :class:`bidfusion.bidrun.quarantine.QuarantineError` (code
    ``INTEGRITY_FAILURE``) if the persisted truth does not check out; the
    caller (the Flask route) turns that into a safe, static 409 response.
    """
    result = read_quarantine_package(package_directory)
    manifest = result.manifest
    files = tuple(
        UploadFileRow(
            display_name=file.display_name,
            detected_type=file.detected_type,
            size_label=_format_size(file.size_bytes),
            short_hash=_short_hash(file.sha256),
        )
        for file in manifest.files
    )
    return UploadResultView(
        key=key,
        status=StatusDisplay(label="QUARANTINED", tone="warning", icon="alert"),
        status_message=_STATIC_QUARANTINE_MESSAGE,
        files=files,
        file_count=len(files),
        policy_name=manifest.policy_name,
        policy_version=manifest.policy_version,
        retention_policy=manifest.retention_policy.value,
        deletion_status=manifest.deletion_status.value,
        authorization_status=_STATIC_AUTHORIZATION_STATUS,
        created_at=manifest.created_at.isoformat(),
    )


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _short_hash(sha256_hex: str) -> str:
    return f"{sha256_hex[:_SHORT_HASH_LENGTH]}…"
