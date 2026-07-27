"""Evidence-driven capability matching against governed enterprise knowledge."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, computed_field, model_validator

from bidfusion.schemas.common import (
    BidfusionModel,
    Confidence,
    MatchStatus,
    Severity,
)
from bidfusion.schemas.ids import (
    BidId,
    CapabilityId,
    KnowledgeItemId,
    RequirementId,
)
from bidfusion.schemas.knowledge import (
    KnowledgeApprovalStatus,
    KnowledgeGovernance,
)


class CapabilityKind(StrEnum):
    """Kinds of governed capability records."""

    SERVICE = "SERVICE"
    PRODUCT = "PRODUCT"
    CAPABILITY = "CAPABILITY"
    FEATURE = "FEATURE"
    CERTIFICATION = "CERTIFICATION"
    SLA = "SLA"
    DELIVERY_CAPABILITY = "DELIVERY_CAPABILITY"
    REGION = "REGION"
    REFERENCE = "REFERENCE"
    STANDARD_RESPONSE = "STANDARD_RESPONSE"


class EvidenceReference(BidfusionModel):
    """Governance snapshot used to validate a capability claim."""

    source: Literal["governed_knowledge"] = "governed_knowledge"
    knowledge_item_id: KnowledgeItemId
    capability_id: CapabilityId
    knowledge_version: int = Field(ge=1)
    approval_status: KnowledgeApprovalStatus
    valid_from: datetime
    valid_until: datetime | None = None
    checked_at: datetime
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validity_window_is_coherent(self) -> EvidenceReference:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            msg = "evidence valid_until must follow valid_from"
            raise ValueError(msg)
        return self

    def is_approved_and_valid_at(self, when: datetime) -> bool:
        """Check the governance snapshot at a capability evaluation time."""
        return (
            self.approval_status is KnowledgeApprovalStatus.APPROVED
            and self.valid_from <= when
            and (self.valid_until is None or when < self.valid_until)
        )


class Capability(BidfusionModel):
    """Capability record backed by fully governed enterprise knowledge."""

    capability_id: CapabilityId
    knowledge_item_id: KnowledgeItemId
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: CapabilityKind
    limitations: list[str] = Field(default_factory=list)
    governance: KnowledgeGovernance


class CapabilityMatch(BidfusionModel):
    """Evidence-backed match between one bid requirement and governed knowledge."""

    bid_id: BidId
    requirement_id: RequirementId
    status: MatchStatus
    capability_id: CapabilityId | None = None
    confidence: Confidence
    evaluated_at: datetime
    evidence: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    limitations: list[str] = Field(default_factory=list)
    requires_sme_review: bool = False

    @model_validator(mode="after")
    def _positive_claim_needs_valid_approved_evidence(self) -> CapabilityMatch:
        """Enforce: no valid, approved evidence means no positive capability claim."""
        positive = self.status in (MatchStatus.SUPPORTED, MatchStatus.PARTIALLY_SUPPORTED)
        if not positive:
            return self
        if self.capability_id is None:
            msg = f"status {self.status.value} requires a capability_id"
            raise ValueError(msg)
        if not self.evidence:
            msg = f"status {self.status.value} requires at least one evidence reference"
            raise ValueError(msg)
        for evidence in self.evidence:
            if evidence.capability_id != self.capability_id:
                msg = "positive match evidence must reference the matched capability"
                raise ValueError(msg)
            if not evidence.is_approved_and_valid_at(self.evaluated_at):
                msg = "positive match evidence must be approved and valid when evaluated"
                raise ValueError(msg)
            if evidence.checked_at > self.evaluated_at:
                msg = "positive match evidence must be checked no later than evaluation"
                raise ValueError(msg)
        return self


class CoverageResult(BidfusionModel):
    """Coverage summary whose counters are derived from isolated matches."""

    bid_id: BidId
    matches: tuple[CapabilityMatch, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _matches_are_bid_isolated_and_unique(self) -> CoverageResult:
        if any(match.bid_id != self.bid_id for match in self.matches):
            msg = "coverage matches must belong to the coverage bid"
            raise ValueError(msg)
        requirement_ids = [match.requirement_id for match in self.matches]
        if len(requirement_ids) != len(set(requirement_ids)):
            msg = "coverage may contain only one match per requirement"
            raise ValueError(msg)
        return self

    @computed_field
    def total_requirements(self) -> int:
        return len(self.matches)

    @computed_field
    def supported(self) -> int:
        return sum(match.status is MatchStatus.SUPPORTED for match in self.matches)

    @computed_field
    def partially_supported(self) -> int:
        return sum(match.status is MatchStatus.PARTIALLY_SUPPORTED for match in self.matches)

    @computed_field
    def not_supported(self) -> int:
        return sum(match.status is MatchStatus.NOT_SUPPORTED for match in self.matches)

    @computed_field
    def unknown(self) -> int:
        return sum(match.status is MatchStatus.UNKNOWN for match in self.matches)


class GapStatus(StrEnum):
    """Lifecycle of an identified capability gap."""

    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    ACCEPTED = "ACCEPTED"


class Gap(BidfusionModel):
    """A requirement that is not or only partially covered."""

    gap_id: str = Field(min_length=1)
    bid_id: BidId
    requirement_id: RequirementId
    description: str | None = None
    severity: Severity = Severity.MEDIUM
    recommended_action: str | None = None
    status: GapStatus = GapStatus.OPEN
