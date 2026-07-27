"""Quality assurance and human review contracts (Domains H and I).

Quality findings prefer UNKNOWN / UNCLEAR / REQUIRES_REVIEW over invented
information. Human corrections are persisted so they can later feed
evaluations.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.common import BidfusionModel, Severity
from bidfusion.schemas.ids import ActorId, BidId, ReviewId
from bidfusion.schemas.provenance import SourceReference


class QualityCategory(StrEnum):
    """Category of a quality finding."""

    MISSING_PAGES = "MISSING_PAGES"
    PARSING_ERROR = "PARSING_ERROR"
    OCR_QUALITY = "OCR_QUALITY"
    EXTRACTION_COVERAGE = "EXTRACTION_COVERAGE"
    REQUIREMENT_COVERAGE = "REQUIREMENT_COVERAGE"
    MISSING_SOURCE = "MISSING_SOURCE"
    CONFLICTING_INFORMATION = "CONFLICTING_INFORMATION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MISSING_MANDATORY = "MISSING_MANDATORY"
    CROSS_REFERENCE_ERROR = "CROSS_REFERENCE_ERROR"
    DEADLINE_CONFLICT = "DEADLINE_CONFLICT"


class FindingStatus(StrEnum):
    """Lifecycle of a quality finding."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class QualityFinding(BidfusionModel):
    """A single finding of the quality gate."""

    finding_id: str
    bid_id: BidId
    severity: Severity
    category: QualityCategory
    message: str
    source: SourceReference | None = None
    related_ids: list[str] = Field(
        default_factory=list,
        description="IDs of related objects, e.g. requirement_ids or document_ids",
    )
    status: FindingStatus = FindingStatus.OPEN

    @model_validator(mode="after")
    def _source_is_bid_isolated(self) -> QualityFinding:
        if self.source is not None and self.source.bid_id != self.bid_id:
            msg = "quality finding source must belong to the finding bid"
            raise ValueError(msg)
        return self


class ReviewDecision(StrEnum):
    """Decision of a human reviewer on a review subject."""

    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"


class FieldCorrection(BidfusionModel):
    """Structured field-level correction made during extraction validation."""

    field_path: str = Field(min_length=1)
    original_value: str | None = None
    corrected_value: str


class HumanReview(BidfusionModel):
    """Persisted validation or correction of AI/extraction output.

    This is deliberately distinct from cross-functional ``BusinessReview``
    and ``Approval`` contracts in ``schemas.business``.
    """

    review_id: ReviewId
    bid_id: BidId
    subject_type: str = Field(
        description='Type of the reviewed object, e.g. "requirement", "deadline", "match"',
    )
    subject_id: str = Field(description="ID of the reviewed object")
    decision: ReviewDecision
    reviewer: ActorId
    reviewed_at: datetime
    comment: str | None = None
    corrections: tuple[FieldCorrection, ...] = Field(default_factory=tuple)
    sources: tuple[SourceReference, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _correction_decision_has_changes(self) -> HumanReview:
        if any(source.bid_id != self.bid_id for source in self.sources):
            msg = "extraction review sources must belong to the review bid"
            raise ValueError(msg)
        if self.decision is ReviewDecision.CORRECTED and not self.corrections:
            msg = "CORRECTED extraction reviews require structured corrections"
            raise ValueError(msg)
        if self.decision is not ReviewDecision.CORRECTED and self.corrections:
            msg = "structured corrections require a CORRECTED decision"
            raise ValueError(msg)
        return self
