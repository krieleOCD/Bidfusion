"""BidRun lifecycle: the fachlich (business-facing) wrapper around one bid
attempt, from an unknown upload to a processed, reviewed result.

Distinct from the existing technical ``ProcessingRun``
(:mod:`bidfusion.schemas.processing`): a BidRun owns upload, quarantine,
security-review, and human-review progress and may, in later slices,
reference more than one technical ``ProcessingRun``. See
docs/architecture/level-1-target.md for the full contract.
"""

from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY, UploadPolicy
from bidfusion.bidrun.quarantine import (
    AUTHORIZATION_NOT_ACCEPTED,
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
    ReadableStream,
    UploadedFileInput,
    quarantine_upload,
    read_quarantine_package,
)
from bidfusion.bidrun.transitions import (
    ALLOWED_TRANSITIONS,
    WORKFLOW_NAME,
    WORKFLOW_VERSION,
    IllegalBidRunTransitionError,
    apply_transition,
    create_bid_run,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AUTHORIZATION_NOT_ACCEPTED",
    "DEFAULT_UPLOAD_POLICY",
    "DUPLICATE_DISPLAY_NAME",
    "EMPTY_PACKAGE",
    "EXTENSION_NOT_ALLOWED",
    "FILE_TOO_LARGE",
    "GENERIC_QUARANTINE_ERROR",
    "INTEGRITY_FAILURE",
    "INVALID_FILENAME",
    "MACRO_CONTENT_DETECTED",
    "PACKAGE_TOO_LARGE",
    "QUARANTINE_ROOT_INVALID",
    "STORAGE_ERROR",
    "TOO_MANY_FILES",
    "TYPE_MISMATCH",
    "WORKFLOW_NAME",
    "WORKFLOW_VERSION",
    "IllegalBidRunTransitionError",
    "QuarantineError",
    "QuarantineResult",
    "ReadableStream",
    "UploadPolicy",
    "UploadedFileInput",
    "apply_transition",
    "create_bid_run",
    "quarantine_upload",
    "read_quarantine_package",
]
