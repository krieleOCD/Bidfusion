"""BidRun lifecycle: the fachlich (business-facing) wrapper around one bid
attempt, from an unknown upload to a processed, reviewed result.

Distinct from the existing technical ``ProcessingRun``
(:mod:`bidfusion.schemas.processing`): a BidRun owns upload, quarantine,
security-review, and human-review progress and may, in later slices,
reference more than one technical ``ProcessingRun``. See
docs/architecture/level-1-target.md for the full contract.
"""

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
    "WORKFLOW_NAME",
    "WORKFLOW_VERSION",
    "IllegalBidRunTransitionError",
    "apply_transition",
    "create_bid_run",
]
