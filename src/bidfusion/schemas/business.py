"""Minimal APMP-aligned opportunity, responsibility, and governance contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.common import BidfusionModel, Severity
from bidfusion.schemas.ids import (
    ActorId,
    BidId,
    OpportunityId,
    ReviewId,
)
from bidfusion.schemas.provenance import SourceReference


class Opportunity(BidfusionModel):
    """Upstream commercial opportunity, separate from RFP processing."""

    opportunity_id: OpportunityId
    name: str = Field(min_length=1)
    customer: str | None = None
    created_at: datetime
    external_reference: str | None = None


class BidDecisionStatus(StrEnum):
    """Qualification decision reserved without implementing a scoring engine."""

    PENDING = "PENDING"
    GO = "GO"
    NO_GO = "NO_GO"
    CONDITIONAL = "CONDITIONAL"


class BidDecision(BidfusionModel):
    """Auditable business qualification decision for a bid."""

    bid_id: BidId
    status: BidDecisionStatus = BidDecisionStatus.PENDING
    decided_by: ActorId | None = None
    decided_at: datetime | None = None
    rationale: str | None = Field(default=None, min_length=1)
    conditions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _decision_audit_is_complete(self) -> BidDecision:
        audit_fields = (self.decided_by, self.decided_at, self.rationale)
        if self.status is BidDecisionStatus.PENDING and any(audit_fields):
            msg = "pending bid decisions cannot carry completed decision audit fields"
            raise ValueError(msg)
        if self.status is not BidDecisionStatus.PENDING and not all(audit_fields):
            msg = "completed bid decisions require actor, timestamp, and rationale"
            raise ValueError(msg)
        if self.status is BidDecisionStatus.CONDITIONAL and not self.conditions:
            msg = "conditional bid decisions require at least one condition"
            raise ValueError(msg)
        return self


class ActorType(StrEnum):
    """Responsibility-bearing actor; this is not an IAM or RBAC model."""

    PERSON = "PERSON"
    TEAM = "TEAM"
    SYSTEM = "SYSTEM"


class Actor(BidfusionModel):
    """Minimal reusable responsibility holder."""

    actor_id: ActorId
    display_name: str = Field(min_length=1)
    actor_type: ActorType


class AssignmentSubject(StrEnum):
    """Supported ownership targets at the Foundation boundary."""

    REQUIREMENT = "REQUIREMENT"
    COMPLIANCE_ITEM = "COMPLIANCE_ITEM"
    SME_TASK = "SME_TASK"
    REVIEW = "REVIEW"
    APPROVAL = "APPROVAL"
    KNOWLEDGE_ITEM = "KNOWLEDGE_ITEM"


class Assignment(BidfusionModel):
    """Auditable assignment of one actor to one responsibility."""

    bid_id: BidId | None = None
    actor_id: ActorId
    subject_type: AssignmentSubject
    subject_id: str = Field(min_length=1)
    responsibility: str = Field(min_length=1)
    assigned_at: datetime
    assigned_by: ActorId


class BusinessReviewType(StrEnum):
    """Business governance discipline, distinct from extraction validation."""

    TECHNICAL = "TECHNICAL"
    LEGAL = "LEGAL"
    SECURITY = "SECURITY"
    COMMERCIAL = "COMMERCIAL"
    FINAL = "FINAL"


class BusinessReviewStatus(StrEnum):
    """Minimal state of a business review."""

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ReviewFinding(BidfusionModel):
    """Finding raised by a business review."""

    finding_id: str = Field(min_length=1)
    review_id: ReviewId
    bid_id: BidId
    severity: Severity
    message: str = Field(min_length=1)
    sources: tuple[SourceReference, ...] = Field(default_factory=tuple)


class ApprovalDecision(StrEnum):
    """Recorded business approval outcome."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONDITIONAL = "CONDITIONAL"


class Approval(BidfusionModel):
    """Audited business sign-off associated with a review."""

    review_id: ReviewId
    bid_id: BidId
    approver_id: ActorId
    decision: ApprovalDecision
    decided_at: datetime
    rationale: str = Field(min_length=1)
    conditions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _conditional_approval_has_conditions(self) -> Approval:
        if self.decision is ApprovalDecision.CONDITIONAL and not self.conditions:
            msg = "conditional approvals require at least one condition"
            raise ValueError(msg)
        return self


class BusinessReview(BidfusionModel):
    """Cross-functional business review, not an AI correction record."""

    review_id: ReviewId
    bid_id: BidId
    review_type: BusinessReviewType
    owner_id: ActorId
    status: BusinessReviewStatus = BusinessReviewStatus.PLANNED
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    findings: tuple[ReviewFinding, ...] = Field(default_factory=tuple)
    approvals: tuple[Approval, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _review_children_are_isolated(self) -> BusinessReview:
        for finding in self.findings:
            if finding.bid_id != self.bid_id or finding.review_id != self.review_id:
                msg = "review findings must belong to their parent review and bid"
                raise ValueError(msg)
            if any(source.bid_id != self.bid_id for source in finding.sources):
                msg = "review finding sources must belong to the review bid"
                raise ValueError(msg)
        for approval in self.approvals:
            if approval.bid_id != self.bid_id or approval.review_id != self.review_id:
                msg = "approvals must belong to their parent review and bid"
                raise ValueError(msg)
        if self.status is BusinessReviewStatus.COMPLETED and self.completed_at is None:
            msg = "completed business reviews require completed_at"
            raise ValueError(msg)
        return self
