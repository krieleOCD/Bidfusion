"""Governed enterprise knowledge, kept separate from bid-specific data."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.common import BidfusionModel, DataClassification
from bidfusion.schemas.ids import ActorId, KnowledgeItemId


class KnowledgeApprovalStatus(StrEnum):
    """Governance state of an enterprise knowledge record."""

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class KnowledgeSourceType(StrEnum):
    """Minimal categories of sources for governed knowledge."""

    INTERNAL_DOCUMENT = "INTERNAL_DOCUMENT"
    POLICY = "POLICY"
    CERTIFICATION = "CERTIFICATION"
    REFERENCE = "REFERENCE"
    CASE_STUDY = "CASE_STUDY"
    OTHER = "OTHER"


class KnowledgeSource(BidfusionModel):
    """Origin of a governed knowledge record."""

    source_type: KnowledgeSourceType
    reference: str = Field(min_length=1)


class KnowledgeEvidence(BidfusionModel):
    """Evidence retained by knowledge governance."""

    evidence_id: str = Field(min_length=1)
    source: KnowledgeSource
    description: str = Field(min_length=1)


class KnowledgeGovernance(BidfusionModel):
    """Ownership, approval, version, validity, and review policy."""

    owner_id: ActorId
    approval_status: KnowledgeApprovalStatus
    version: int = Field(ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    review_cycle_days: int = Field(gt=0)
    classification: DataClassification
    source: KnowledgeSource
    evidence: tuple[KnowledgeEvidence, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _governance_is_coherent(self) -> KnowledgeGovernance:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            msg = "knowledge valid_until must follow valid_from"
            raise ValueError(msg)
        if self.approval_status is KnowledgeApprovalStatus.APPROVED:
            if self.valid_from is None:
                msg = "approved knowledge requires valid_from"
                raise ValueError(msg)
            if not self.evidence:
                msg = "approved knowledge requires evidence"
                raise ValueError(msg)
        return self


class KnowledgeItem(BidfusionModel):
    """Governed enterprise knowledge record; never mutated by bid matching."""

    knowledge_item_id: KnowledgeItemId
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    governance: KnowledgeGovernance
