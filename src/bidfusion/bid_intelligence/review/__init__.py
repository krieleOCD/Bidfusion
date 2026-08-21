"""Human review of requirement knowledge assessments (bid-side).

A human confirms, rejects, or defers one candidate assessment for one
requirement in one bid run. Reviews are immutable, versioned, and bound
to the exact assessment content they judged. Nothing in this package
reads or writes golden knowledge state: confirming a bid-side candidate
never promotes a golden claim.
"""

from bidfusion.bid_intelligence.review.contracts import (
    MAX_RATIONALE_LENGTH,
    MAX_REVIEWER_LENGTH,
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewedAssessmentProjection,
    ReviewedRequirementAssessment,
    ReviewState,
    assessment_digest,
    review_id_for,
)
from bidfusion.bid_intelligence.review.service import (
    ReviewValidationError,
    project_reviewed_assessments,
    record_requirement_assessment_review,
)
from bidfusion.bid_intelligence.review.store import (
    ReviewStoreConflictError,
    ReviewStoreIntegrityError,
    RunReviewStore,
)

__all__ = [
    "MAX_RATIONALE_LENGTH",
    "MAX_REVIEWER_LENGTH",
    "RequirementAssessmentReview",
    "ReviewDecision",
    "ReviewState",
    "ReviewStoreConflictError",
    "ReviewStoreIntegrityError",
    "ReviewValidationError",
    "ReviewedAssessmentProjection",
    "ReviewedRequirementAssessment",
    "RunReviewStore",
    "assessment_digest",
    "project_reviewed_assessments",
    "record_requirement_assessment_review",
    "review_id_for",
]
