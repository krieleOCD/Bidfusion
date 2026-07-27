"""First-class APMP-aligned compliance matrix contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import BidfusionModel, Severity
from bidfusion.schemas.ids import ActorId, BidId, CapabilityId, RequirementId, ReviewId
from bidfusion.schemas.intelligence import EvidenceReference
from bidfusion.schemas.provenance import SourceReference


class ComplianceStatus(StrEnum):
    """Requirement response posture, distinct from capability match status."""

    COMPLIANT = "COMPLIANT"
    PARTIALLY_COMPLIANT = "PARTIALLY_COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    UNKNOWN = "UNKNOWN"
    REQUIRES_CLARIFICATION = "REQUIRES_CLARIFICATION"


class ComplianceResponseStatus(StrEnum):
    """Minimal maturity state of a response."""

    NOT_STARTED = "NOT_STARTED"
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FINAL = "FINAL"


class ComplianceReviewStatus(StrEnum):
    """Business review state for a compliance item."""

    NOT_REVIEWED = "NOT_REVIEWED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"


class ComplianceRisk(BidfusionModel):
    """Risk attached to a compliance posture."""

    severity: Severity
    description: str = Field(min_length=1)


class ComplianceItem(BidfusionModel):
    """Requirement-linked compliance posture with ownership and evidence."""

    compliance_item_id: str = Field(min_length=1)
    bid_id: BidId
    requirement_id: RequirementId
    status: ComplianceStatus = ComplianceStatus.UNKNOWN
    assessed_at: datetime
    capability_ids: tuple[CapabilityId, ...] = Field(default_factory=tuple)
    evidence: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    owner_id: ActorId | None = None
    risk: ComplianceRisk | None = None
    clarification: str | None = Field(default=None, min_length=1)
    response_status: ComplianceResponseStatus = ComplianceResponseStatus.NOT_STARTED
    review_status: ComplianceReviewStatus = ComplianceReviewStatus.NOT_REVIEWED
    review_id: ReviewId | None = None
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _compliance_claim_is_coherent(self) -> ComplianceItem:
        if any(source.bid_id != self.bid_id for source in self.sources):
            msg = "compliance item sources must belong to the item bid"
            raise ValueError(msg)
        positive = self.status in (
            ComplianceStatus.COMPLIANT,
            ComplianceStatus.PARTIALLY_COMPLIANT,
        )
        if positive and not self.evidence:
            msg = "positive compliance status requires governed evidence"
            raise ValueError(msg)
        if positive and any(
            not evidence.is_approved_and_valid_at(self.assessed_at) for evidence in self.evidence
        ):
            msg = "positive compliance status requires approved, current evidence"
            raise ValueError(msg)
        if positive and any(evidence.checked_at > self.assessed_at for evidence in self.evidence):
            msg = "positive compliance evidence must be checked no later than assessment"
            raise ValueError(msg)
        evidence_capabilities = {item.capability_id for item in self.evidence}
        if not evidence_capabilities.issubset(set(self.capability_ids)):
            msg = "compliance evidence must reference a listed capability"
            raise ValueError(msg)
        if self.status is ComplianceStatus.REQUIRES_CLARIFICATION and self.clarification is None:
            msg = "REQUIRES_CLARIFICATION requires clarification text"
            raise ValueError(msg)
        if self.review_status is ComplianceReviewStatus.NOT_REVIEWED and self.review_id:
            msg = "an unreviewed compliance item cannot reference a business review"
            raise ValueError(msg)
        return self


class ComplianceMatrix(BidfusionModel):
    """Versioned compliance aggregate over one normalized bid dataset."""

    artifact: ArtifactEnvelope
    source_dataset: ArtifactReference
    bid_id: BidId
    version: int = Field(default=1, ge=1)
    items: tuple[ComplianceItem, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _matrix_is_isolated_and_lineaged(self) -> ComplianceMatrix:
        if self.artifact.artifact_type is not ArtifactType.COMPLIANCE_MATRIX:
            msg = "compliance matrices require a compliance_matrix artifact"
            raise ValueError(msg)
        if self.source_dataset.artifact_type is not ArtifactType.NORMALIZED_BID_DATASET:
            msg = "compliance matrix source must be a normalized_bid_dataset"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.source_dataset.bid_id != self.bid_id:
            msg = "compliance matrix artifacts must belong to the matrix bid"
            raise ValueError(msg)
        input_ids = {item.artifact_id for item in self.artifact.input_artifacts}
        if self.source_dataset.artifact_id not in input_ids:
            msg = "compliance matrix lineage must include its normalized dataset"
            raise ValueError(msg)
        if any(item.bid_id != self.bid_id for item in self.items):
            msg = "compliance items must belong to the matrix bid"
            raise ValueError(msg)
        requirement_ids = [item.requirement_id for item in self.items]
        if len(requirement_ids) != len(set(requirement_ids)):
            msg = "compliance matrix may contain only one item per requirement"
            raise ValueError(msg)
        return self
