"""Security Gate result and hash-bound downstream handoff contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import (
    BidfusionModel,
    FrozenDict,
    FrozenMapping,
    SecurityVerdict,
    Severity,
    Sha256Digest,
)
from bidfusion.schemas.ids import ActorId, BidId, DocumentId, ReviewId


class SecurityFinding(BidfusionModel):
    """A single finding produced by one security check."""

    check: str = Field(
        description='Producing check, e.g. "mime_type", "magic_bytes", "prompt_injection"',
    )
    severity: Severity
    message: str = Field(description="Human-readable description of the finding")
    details: FrozenMapping[str, str] = Field(default_factory=FrozenDict)


class SecurityReviewDisposition(StrEnum):
    """Audited disposition of a pending MANUAL_REVIEW verdict."""

    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class SecurityManualReview(BidfusionModel):
    """Explicit human release or rejection of a MANUAL_REVIEW result."""

    review_id: ReviewId
    reviewer_id: ActorId
    disposition: SecurityReviewDisposition
    decided_at: datetime
    rationale: str = Field(min_length=1)


class SecurityResult(BidfusionModel):
    """Security decision bound to an exact immutable artifact and content hash."""

    bid_id: BidId
    document_id: DocumentId
    artifact: ArtifactReference
    content_hash: Sha256Digest
    verdict: SecurityVerdict
    findings: tuple[SecurityFinding, ...] = Field(default_factory=tuple)
    scanner: str = Field(description="Name of the security gate component")
    scanner_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    decided_at: datetime
    manual_review: SecurityManualReview | None = None

    @model_validator(mode="after")
    def _decision_is_bound_and_coherent(self) -> SecurityResult:
        if self.artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "security results must bind a raw_document artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id:
            msg = "security result and artifact must belong to the same bid"
            raise ValueError(msg)
        if self.artifact.content_hash != self.content_hash:
            msg = "security result content hash must match the artifact content hash"
            raise ValueError(msg)
        if self.verdict is SecurityVerdict.MANUAL_REVIEW:
            if self.manual_review is not None and self.manual_review.decided_at < self.decided_at:
                msg = "manual review decision cannot precede the scanner decision"
                raise ValueError(msg)
            return self
        if self.manual_review is not None:
            msg = "manual review audit is only valid for MANUAL_REVIEW"
            raise ValueError(msg)
        return self

    @property
    def allows_processing(self) -> bool:
        """Whether this decision may be wrapped as a downstream clearance."""
        if self.verdict is SecurityVerdict.ALLOW:
            return True
        return (
            self.verdict is SecurityVerdict.MANUAL_REVIEW
            and self.manual_review is not None
            and self.manual_review.disposition is SecurityReviewDisposition.RELEASED
        )


class SecurityClearedArtifact(BidfusionModel):
    """Only admissible raw-content input contract for Document Understanding.

    This contract validates decision semantics and binds the decision to the
    exact artifact ID, bid ID and hash. Runtime API authorization and operational
    scanner isolation remain later enforcement responsibilities.
    """

    artifact: ArtifactReference
    document_id: DocumentId
    security_result: SecurityResult

    @model_validator(mode="after")
    def _requires_exact_passing_result(self) -> SecurityClearedArtifact:
        result = self.security_result
        if result.document_id != self.document_id:
            msg = "clearance and security result must identify the same document"
            raise ValueError(msg)
        if result.artifact != self.artifact:
            msg = "clearance must reference the exact scanned artifact and content hash"
            raise ValueError(msg)
        if result.content_hash != self.artifact.content_hash:
            msg = "clearance hash must match the exact artifact content"
            raise ValueError(msg)
        if not result.allows_processing:
            msg = f"security verdict {result.verdict.value} does not permit processing"
            raise ValueError(msg)
        return self
