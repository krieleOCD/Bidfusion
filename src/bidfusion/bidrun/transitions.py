"""Allowlisted BidRun transitions for the current slice.

Only ``CREATED -> UPLOADED -> QUARANTINED`` is implemented. Every other
edge named in :class:`bidfusion.schemas.bidrun.BidRunState` is described
in docs/architecture/level-1-target.md but has no transition function
here — later slices add their own allowlist entry, reason code, and
operator message when they actually implement a transition, never as a
placeholder ahead of that work.
"""

from __future__ import annotations

from datetime import datetime

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.bidrun import (
    AuthorizationRecord,
    BidRun,
    BidRunReasonCode,
    BidRunState,
    BidRunTransition,
)
from bidfusion.schemas.ids import BidId, RunId

#: Versions the *allowed transition set*, not the code that runs it —
#: see docs/architecture/level-1-target.md, §5.
WORKFLOW_NAME = "bidfusion-level1-bidrun"
WORKFLOW_VERSION = "0.1.0"

#: Static, allowlisted operator-facing text per state. Never derived from
#: an exception, a filename, or any other free-form input.
_OPERATOR_MESSAGES: dict[BidRunState, str] = {
    BidRunState.CREATED: "Bid run created. Waiting for an authorized upload.",
    BidRunState.UPLOADED: "Upload authorized and accepted. Preparing quarantine.",
    BidRunState.QUARANTINED: (
        "Uploaded and quarantined. No parsing or security clearance has occurred."
    ),
}

#: The single source of truth for which transitions exist right now and
#: their reason code; ``ALLOWED_TRANSITIONS`` is derived from this, so
#: the allowlist and the reason codes can never drift apart.
_REASON_CODES: dict[tuple[BidRunState, BidRunState], BidRunReasonCode] = {
    (BidRunState.CREATED, BidRunState.UPLOADED): BidRunReasonCode.FILES_UPLOADED,
    (BidRunState.UPLOADED, BidRunState.QUARANTINED): BidRunReasonCode.PACKAGE_QUARANTINED,
}

ALLOWED_TRANSITIONS: frozenset[tuple[BidRunState, BidRunState]] = frozenset(_REASON_CODES)


class IllegalBidRunTransitionError(ValueError):
    """Raised when a requested BidRun transition is not on the allowlist,
    including a transition timestamped before the run's last update."""


def create_bid_run(
    *,
    bid_id: BidId,
    run_id: RunId,
    authorization: AuthorizationRecord,
    created_at: datetime,
) -> BidRun:
    """Create a fresh BidRun in ``CREATED`` with no recorded transitions.

    ``workflow_name``/``workflow_version`` are always the current
    module's constants — never caller-supplied, so no request parameter
    can steer which workflow identity a BidRun claims.
    """
    return BidRun(
        bid_id=bid_id,
        run_id=run_id,
        workflow_name=WORKFLOW_NAME,
        workflow_version=WORKFLOW_VERSION,
        authorization=authorization,
        source_package_artifact=None,
        current_state=BidRunState.CREATED,
        state_history=(),
        artifact_refs=(),
        created_at=created_at,
        updated_at=created_at,
        terminal_reason=None,
        operator_message=_OPERATOR_MESSAGES[BidRunState.CREATED],
    )


def apply_transition(
    run: BidRun,
    *,
    to: BidRunState,
    occurred_at: datetime,
    authorization: AuthorizationRecord | None = None,
    artifact_refs: tuple[ArtifactReference, ...] | None = None,
    source_package_artifact: ArtifactReference | None = None,
) -> BidRun:
    """Apply one allowlisted transition, returning a new validated BidRun.

    ``to`` is the only caller-chosen part of the transition; the reason
    code and operator message are always derived from the allowlist, so
    no UI parameter can ever inject an arbitrary reason or message.
    Fields left as ``None`` keep their previous value — a transition
    that doesn't touch authorization or artifacts doesn't have to repeat
    them.
    """
    reason_code = _REASON_CODES.get((run.current_state, to))
    if reason_code is None:
        msg = f"{run.current_state.value} -> {to.value} is not an allowed BidRun transition"
        raise IllegalBidRunTransitionError(msg)
    if occurred_at < run.updated_at:
        msg = "a BidRun transition cannot be timestamped before the run's last update"
        raise IllegalBidRunTransitionError(msg)

    transition = BidRunTransition(
        from_state=run.current_state,
        to_state=to,
        reason_code=reason_code,
        occurred_at=occurred_at,
    )
    return BidRun(
        bid_id=run.bid_id,
        run_id=run.run_id,
        workflow_name=run.workflow_name,
        workflow_version=run.workflow_version,
        authorization=authorization if authorization is not None else run.authorization,
        source_package_artifact=(
            source_package_artifact
            if source_package_artifact is not None
            else run.source_package_artifact
        ),
        current_state=to,
        state_history=(*run.state_history, transition),
        artifact_refs=artifact_refs if artifact_refs is not None else run.artifact_refs,
        created_at=run.created_at,
        updated_at=occurred_at,
        terminal_reason=None,
        operator_message=_OPERATOR_MESSAGES[to],
    )
