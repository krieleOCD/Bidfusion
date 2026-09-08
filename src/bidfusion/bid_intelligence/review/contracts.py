"""Bid-side human review contracts for requirement knowledge assessments.

A review is a human decision about **one candidate assessment in one bid
run** — the pairing of one extracted requirement with its golden
candidate match. It is deliberately not a statement about the golden
knowledge itself: confirming a candidate here never touches, validates,
or promotes the underlying golden ``CapabilityClaim``, whose only paths
out of ``EXTRACTED_UNVERIFIED`` remain the explicit golden-domain
functions that this package never calls.

Reviews are immutable, attributable, and version-bound. A review is tied
to the exact assessment it was made against three ways: the
content-derived ``assessment_id``, the assessment schema
``assessment_version``, and a SHA-256 ``assessment_digest`` over the
complete serialized assessment. If any of the three no longer matches
the current assessment — the requirement text changed, the schema moved,
or the candidate match itself changed with a new knowledge snapshot —
the review is stale and is never presented as a review of the newer
assessment.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated

from pydantic import Field, model_validator

from bidfusion.bid_intelligence.matching.contracts import RequirementKnowledgeAssessment
from bidfusion.schemas.common import BidfusionModel, SemanticVersion, Sha256Digest
from bidfusion.schemas.ids import BidId, RequirementId, RunId

#: Review identifiers are derived from content hashes like every other
#: BidFusion identifier family and share no format with golden IDs.
ReviewId = Annotated[str, Field(pattern=r"^REV-[0-9a-f]{12}$")]

MAX_REVIEWER_LENGTH = 120
MAX_RATIONALE_LENGTH = 2000


class ReviewDecision(StrEnum):
    """Closed vocabulary of bid-side review outcomes.

    ``CONFIRMED`` — a human accepts this candidate assessment for this
    requirement in this bid context. ``REJECTED`` — a human rejects this
    candidate assessment. ``NEEDS_CLARIFICATION`` — a human cannot yet
    resolve it. None of these change a golden claim.
    """

    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class ReviewState(StrEnum):
    """Review dimension of a projected assessment; PENDING = no review."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


def assessment_digest(assessment: RequirementKnowledgeAssessment) -> str:
    """Canonical digest binding a review to one exact assessment.

    Computed over the complete serialized assessment, so a change in
    *anything* — text, hints, match status, evidence — yields a new
    digest and retires every earlier review into stale history.
    """
    return sha256(assessment.model_dump_json().encode("utf-8")).hexdigest()


def review_id_for(assessment_id: str, review_version: int) -> str:
    """Deterministic review identifier for one assessment revision."""
    digest = sha256(f"{assessment_id}|{review_version}".encode()).hexdigest()
    return f"REV-{digest[:12]}"


class RequirementAssessmentReview(BidfusionModel):
    """One immutable, attributable human decision on one assessment.

    Frozen and closed like every BidFusion contract: no metadata dict,
    no filesystem path, no source-section text. ``review_version``
    counts revisions for the same ``assessment_id`` within one run;
    earlier versions are never overwritten.
    """

    review_id: ReviewId
    review_version: int = Field(ge=1)
    assessment_id: str = Field(pattern=r"^RKA-[0-9a-f]{12}$")
    assessment_version: SemanticVersion
    assessment_digest: Sha256Digest
    requirement_id: RequirementId
    bid_id: BidId
    run_id: RunId
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=MAX_REVIEWER_LENGTH)
    rationale: str | None = Field(default=None, min_length=1, max_length=MAX_RATIONALE_LENGTH)
    reviewed_at: datetime

    @model_validator(mode="after")
    def _review_is_canonical(self) -> RequirementAssessmentReview:
        if self.reviewed_at.tzinfo is None:
            msg = "a review timestamp must be timezone-aware"
            raise ValueError(msg)
        if not self.reviewer.strip():
            msg = "a review requires a non-blank reviewer"
            raise ValueError(msg)
        if self.review_id != review_id_for(self.assessment_id, self.review_version):
            msg = "review_id must be derived from the assessment and review version"
            raise ValueError(msg)
        return self


class ReviewedRequirementAssessment(BidfusionModel):
    """One assessment together with its latest *applicable* human review.

    Pure combination — neither side is rewritten, and the candidate
    match status and the human decision stay two visibly separate
    dimensions. ``review`` is ``None`` while the assessment is pending
    or when every stored review is stale for the current assessment.
    """

    assessment: RequirementKnowledgeAssessment
    review: RequirementAssessmentReview | None = None

    @model_validator(mode="after")
    def _review_matches_assessment_exactly(self) -> ReviewedRequirementAssessment:
        if self.review is None:
            return self
        if (
            self.review.assessment_id != self.assessment.assessment_id
            or self.review.assessment_version != self.assessment.assessment_version
            or self.review.assessment_digest != assessment_digest(self.assessment)
        ):
            msg = "a projected review must match the exact assessment it reviewed"
            raise ValueError(msg)
        return self

    @property
    def review_state(self) -> ReviewState:
        """The human-review dimension, distinct from the match status."""
        if self.review is None:
            return ReviewState.PENDING
        return ReviewState(self.review.decision.value)


class ReviewedAssessmentProjection(BidfusionModel):
    """The reviewed working-package input: every assessment plus counts."""

    assessment_version: SemanticVersion
    reviewed: tuple[ReviewedRequirementAssessment, ...] = Field(default_factory=tuple)

    @property
    def counts(self) -> dict[ReviewState, int]:
        """How many assessments sit in each review state."""
        result = dict.fromkeys(ReviewState, 0)
        for item in self.reviewed:
            result[item.review_state] += 1
        return result
