"""BidRun: the business-facing lifecycle of one bid attempt from an
unknown upload to a processed, reviewed result.

``BidRun`` is additive and deliberately distinct from two existing
contracts: ``Bid``/``BidBusinessState`` (qualification and submission
lifecycle, :mod:`bidfusion.schemas.bid`) and ``ProcessingRun``/
``ProcessingStage`` (one technical pipeline execution,
:mod:`bidfusion.schemas.processing`, see
docs/architecture/state-machine.md). A BidRun owns the upload,
quarantine, security-review, and human-review lifecycle around a bid
attempt; the existing technical ``ProcessingRun`` is unchanged and, in
later slices, a BidRun may reference more than one of them (e.g. a rerun
after a fix) without changing its own identity.

This module defines contracts only — the ten target ``BidRunState``
values, the transition record shape, and structural coherence
invariants. Transition *policy* — which state changes are currently
allowed, their reason codes, and their operator-safe messages — lives in
:mod:`bidfusion.bidrun.transitions`, keeping this module free of
workflow policy the same way every other ``schemas/*`` module is free of
the domain logic that produces its contracts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel, SemanticVersion
from bidfusion.schemas.ids import BidId, RunId


class BidRunState(StrEnum):
    """Full target lifecycle (docs/architecture/level-1-target.md, §6).

    Only ``CREATED -> UPLOADED -> QUARANTINED`` is reachable through
    :mod:`bidfusion.bidrun.transitions` in the current slice. The
    remaining states are named now so this contract never needs a
    breaking change to grow into them; their transitions are not
    simulated ahead of the slice that implements them.
    """

    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    QUARANTINED = "QUARANTINED"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


#: States that exist only before any package has been quarantined; every
#: other state requires a ``source_package_artifact`` to exist.
_PRE_PACKAGE_STATES = frozenset({BidRunState.CREATED, BidRunState.UPLOADED})

#: Terminal states: the current slice's allowlist cannot reach any of
#: these, but the contract already forbids a further transition once one
#: is recorded, and requires the terminal_reason that explains why.
TERMINAL_BIDRUN_STATES = frozenset({BidRunState.BLOCKED, BidRunState.COMPLETED, BidRunState.FAILED})


class BidRunReasonCode(StrEnum):
    """Stable, allowlisted reasons for a recorded BidRun transition.

    Only reasons for transitions implemented in the current slice exist;
    later slices add members additively as their transitions land, never
    speculatively ahead of the code that produces them.
    """

    FILES_UPLOADED = "FILES_UPLOADED"
    PACKAGE_QUARANTINED = "PACKAGE_QUARANTINED"


class AuthorizationType(StrEnum):
    """Closed vocabulary of authorization statements a BidRun can record."""

    NON_PRODUCTION_TEST_CONFIRMATION = "non_production_test_confirmation"


class AuthorizationRecord(BidfusionModel):
    """Structured, explicit user consent — never inferred, never defaulted.

    ``actor`` is the non-authenticated local demonstration identity
    documented in docs/architecture/level-1-target.md (§3, §6) — not a
    real identity claim.
    """

    authorization_type: AuthorizationType
    accepted: bool
    accepted_at: datetime | None = None
    scope: str = Field(min_length=1)
    policy_version: SemanticVersion
    actor: str = Field(default="local-operator", min_length=1)

    @model_validator(mode="after")
    def _acceptance_and_timestamp_are_coherent(self) -> AuthorizationRecord:
        if self.accepted and self.accepted_at is None:
            msg = "an accepted authorization must record when it was accepted"
            raise ValueError(msg)
        if not self.accepted and self.accepted_at is not None:
            msg = "a not-accepted authorization cannot carry an acceptance timestamp"
            raise ValueError(msg)
        return self


class BidRunTransition(BidfusionModel):
    """One recorded, timestamped, reason-coded BidRun state change."""

    from_state: BidRunState
    to_state: BidRunState
    reason_code: BidRunReasonCode
    occurred_at: datetime


class BidRun(BidfusionModel):
    """Versioned, auditable lifecycle of one bid attempt above the
    technical pipeline. See the module docstring for the distinction
    from ``Bid`` and ``ProcessingRun``.
    """

    bid_id: BidId
    run_id: RunId
    workflow_name: str = Field(min_length=1)
    workflow_version: SemanticVersion
    authorization: AuthorizationRecord
    source_package_artifact: ArtifactReference | None = None
    current_state: BidRunState
    state_history: tuple[BidRunTransition, ...] = Field(default_factory=tuple)
    artifact_refs: tuple[ArtifactReference, ...] = Field(default_factory=tuple)
    created_at: datetime
    updated_at: datetime
    terminal_reason: str | None = None
    operator_message: str = Field(min_length=1)

    @model_validator(mode="after")
    def _bidrun_is_coherent(self) -> BidRun:
        if self.updated_at < self.created_at:
            msg = "updated_at cannot precede created_at"
            raise ValueError(msg)
        self._check_history_chain()
        self._check_artifact_refs()
        self._check_source_package()
        self._check_terminal_reason()
        if self.current_state is not BidRunState.CREATED and not self.authorization.accepted:
            msg = f"{self.current_state.value} requires an accepted authorization"
            raise ValueError(msg)
        return self

    def _check_history_chain(self) -> None:
        if not self.state_history:
            if self.current_state is not BidRunState.CREATED:
                msg = "a BidRun without recorded transitions must still be CREATED"
                raise ValueError(msg)
            return
        first = self.state_history[0]
        if first.from_state is not BidRunState.CREATED:
            msg = "the first recorded transition must start from CREATED"
            raise ValueError(msg)
        previous_time = self.created_at
        previous_to: BidRunState = first.from_state
        for transition in self.state_history:
            if transition.from_state is not previous_to:
                msg = "state history is not a contiguous chain"
                raise ValueError(msg)
            if transition.occurred_at < previous_time:
                msg = "state history timestamps cannot move backwards"
                raise ValueError(msg)
            previous_time = transition.occurred_at
            previous_to = transition.to_state
        if self.state_history[-1].to_state is not self.current_state:
            msg = "state history must end at current_state"
            raise ValueError(msg)

    def _check_artifact_refs(self) -> None:
        artifact_ids = [artifact.artifact_id for artifact in self.artifact_refs]
        if len(artifact_ids) != len(set(artifact_ids)):
            msg = "artifact_refs cannot contain duplicate artifact IDs"
            raise ValueError(msg)
        for artifact in self.artifact_refs:
            if artifact.bid_id != self.bid_id or artifact.run_id != self.run_id:
                msg = "artifact_refs must carry the same bid_id and run_id as the BidRun"
                raise ValueError(msg)

    def _check_source_package(self) -> None:
        if self.source_package_artifact is None:
            if self.current_state not in _PRE_PACKAGE_STATES:
                msg = f"{self.current_state.value} requires a source_package_artifact"
                raise ValueError(msg)
            return
        if self.source_package_artifact not in self.artifact_refs:
            msg = "source_package_artifact must also be listed in artifact_refs"
            raise ValueError(msg)

    def _check_terminal_reason(self) -> None:
        is_terminal = self.current_state in TERMINAL_BIDRUN_STATES
        if is_terminal and not self.terminal_reason:
            msg = f"terminal state {self.current_state.value} requires a terminal_reason"
            raise ValueError(msg)
        if not is_terminal and self.terminal_reason is not None:
            msg = "terminal_reason is only valid in a terminal state"
            raise ValueError(msg)
