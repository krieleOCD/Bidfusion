"""Application service for the free-upload flow.

Presentation-side orchestration only, mirroring
:mod:`bidfusion.local_ui.service` for the synthetic fixture flow: this
module owns no filesystem, hashing, or state-machine logic of its own —
it assembles the inputs the framework-free quarantine service
(:mod:`bidfusion.bidrun.quarantine`) needs, and translates its
allowlisted failures into a UI-safe validation error. It never reads
document content and never imports Flask/Werkzeug.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from bidfusion.bidrun import (
    AUTHORIZATION_NOT_ACCEPTED,
    DEFAULT_UPLOAD_POLICY,
    DUPLICATE_DISPLAY_NAME,
    EMPTY_PACKAGE,
    EXTENSION_NOT_ALLOWED,
    FILE_TOO_LARGE,
    GENERIC_QUARANTINE_ERROR,
    INTEGRITY_FAILURE,
    INVALID_FILENAME,
    MACRO_CONTENT_DETECTED,
    PACKAGE_TOO_LARGE,
    QUARANTINE_ROOT_INVALID,
    STORAGE_ERROR,
    TOO_MANY_FILES,
    TYPE_MISMATCH,
    QuarantineError,
    QuarantineResult,
    UploadedFileInput,
    quarantine_upload,
)
from bidfusion.schemas.bidrun import AuthorizationRecord, AuthorizationType
from bidfusion.shared.identifiers import run_id_for

#: Fixed, allowlisted authorization scope/policy/identity — never taken
#: from a free browser field (docs/architecture/level-1-target.md, §6).
AUTHORIZATION_SCOPE = "non-production-internal-test"
AUTHORIZATION_POLICY_VERSION = "0.1.0"
AUTHORIZATION_ACTOR = "local-operator"

#: The exact confirmation text the UI must show next to the checkbox.
AUTHORIZATION_STATEMENT = (
    "I confirm that these files are authorized for non-production testing "
    "and contain no prohibited production customer data."
)

#: Flask's outer, framework-level body-size backstop. The upload policy
#: in ``bidrun.policy`` remains the authoritative per-file/package check;
#: this only bounds the raw multipart body a small, documented amount
#: above the package limit.
_MULTIPART_OVERHEAD_PER_FILE_BYTES = 1024
_MULTIPART_FIXED_OVERHEAD_BYTES = 8192
MAX_CONTENT_LENGTH = (
    DEFAULT_UPLOAD_POLICY.max_package_size_bytes
    + DEFAULT_UPLOAD_POLICY.max_files_per_package * _MULTIPART_OVERHEAD_PER_FILE_BYTES
    + _MULTIPART_FIXED_OVERHEAD_BYTES
)

#: Static, allowlisted UI messages per quarantine error code. Never a raw
#: exception, filename, or path — see FEHLERDARSTELLUNG in the governing
#: instructions for the required minimum distinctions.
_UI_ERROR_MESSAGES: dict[str, str] = {
    AUTHORIZATION_NOT_ACCEPTED: "Please confirm the authorization statement before uploading.",
    EMPTY_PACKAGE: "Select at least one file to upload.",
    EXTENSION_NOT_ALLOWED: (
        "One of the selected files has an unsupported file type. "
        "Only PDF, XLSX, and TXT are accepted."
    ),
    TYPE_MISMATCH: "One of the selected files' content does not match its file extension.",
    MACRO_CONTENT_DETECTED: (
        "One of the selected files contains macro content, which is never accepted."
    ),
    INVALID_FILENAME: "One of the selected files has a filename that cannot be accepted.",
    DUPLICATE_DISPLAY_NAME: (
        "Two or more selected files have the same name. Rename one and try again."
    ),
    FILE_TOO_LARGE: "One of the selected files exceeds the per-file size limit (25 MB).",
    PACKAGE_TOO_LARGE: "The selected files together exceed the package size limit (100 MB).",
    TOO_MANY_FILES: "Too many files selected. The limit is 20 files per package.",
    QUARANTINE_ROOT_INVALID: "The quarantine service is temporarily unavailable. Please try again.",
    STORAGE_ERROR: "The quarantine service is temporarily unavailable. Please try again.",
    INTEGRITY_FAILURE: "This package failed an integrity check and cannot be displayed.",
    GENERIC_QUARANTINE_ERROR: "The upload was rejected. No files were stored.",
}


def ui_message_for(error_code: str) -> str:
    """Static, operator-safe UI text for one allowlisted error code."""
    return _UI_ERROR_MESSAGES.get(error_code, _UI_ERROR_MESSAGES[GENERIC_QUARANTINE_ERROR])


class UploadValidationError(RuntimeError):
    """A free upload was rejected; ``error_code`` is stable and allowlisted.

    The message is always the static UI text for that code — never a raw
    exception, filename, or path.
    """

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(ui_message_for(error_code))


_bid_sequence_lock = threading.Lock()
_bid_sequence = 0


def _next_bid_id(now: datetime) -> str:
    """Allocate a fresh, process-unique bid_id for one upload attempt.

    Deliberately independent of the UI's session-navigation registry —
    bid identity is a property of the upload itself, not of how many
    records the UI happens to keep for navigation.
    """
    global _bid_sequence
    with _bid_sequence_lock:
        _bid_sequence += 1
        sequence = _bid_sequence
    if sequence > 999_999:
        msg = "the local upload service supports at most 999999 uploads per process"
        raise RuntimeError(msg)
    return f"BID-{now.year:04d}-{sequence:06d}"


def submit_upload(
    *,
    files: Sequence[UploadedFileInput],
    authorization_confirmed: bool,
    quarantine_root: Path,
    now: datetime | None = None,
) -> QuarantineResult:
    """Validate an authorized free upload and quarantine it.

    ``authorization_confirmed`` must come from an explicit, never
    pre-selected checkbox; this function never infers consent. On any
    rejection — including a missing confirmation — no ``AuthorizationRecord``
    is even constructed with ``accepted=True``, no BidRun is created, and
    no package directory is written.
    """
    if not authorization_confirmed:
        raise UploadValidationError(AUTHORIZATION_NOT_ACCEPTED)

    started = now if now is not None else datetime.now(UTC)
    authorization = AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=True,
        accepted_at=started,
        scope=AUTHORIZATION_SCOPE,
        policy_version=AUTHORIZATION_POLICY_VERSION,
        actor=AUTHORIZATION_ACTOR,
    )
    bid_id = _next_bid_id(started)
    run_id = run_id_for(started)
    try:
        return quarantine_upload(
            bid_id=bid_id,
            run_id=run_id,
            authorization=authorization,
            files=files,
            quarantine_root=quarantine_root,
            now=started,
        )
    except QuarantineError as failure:
        raise UploadValidationError(failure.error_code) from None
