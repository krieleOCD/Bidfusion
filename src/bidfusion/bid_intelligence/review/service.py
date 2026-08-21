"""Recording and projecting human reviews of requirement assessments.

The service is deliberately narrow and pure: it turns one existing
assessment plus one human decision into one immutable
:class:`RequirementAssessmentReview`, and it projects assessments with
their latest applicable reviews. It mutates nothing — not the
assessment, not any golden claim, not any store — and it never imports
golden claim-confirmation helpers or the golden runtime store.

Versioning is append-only: a repeated review of the same assessment gets
the next ``review_version``; earlier decisions remain on record. A
review recorded against an older assessment digest is *stale history*:
it stays stored but is never projected onto the changed assessment.
"""

from __future__ import annotations

from datetime import datetime

from bidfusion.bid_intelligence.matching.contracts import (
    RequirementKnowledgeAssessment,
)
from bidfusion.bid_intelligence.review.contracts import (
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewedAssessmentProjection,
    ReviewedRequirementAssessment,
    assessment_digest,
    review_id_for,
)
from bidfusion.golden_dataset.contracts import HumanReviewStatus


class ReviewValidationError(ValueError):
    """A review request was rejected; the message is static and safe."""


def record_requirement_assessment_review(
    assessment: RequirementKnowledgeAssessment,
    *,
    decision: ReviewDecision,
    reviewer: str,
    rationale: str | None,
    reviewed_at: datetime,
    run_id: str,
    existing: tuple[RequirementAssessmentReview, ...] = (),
) -> RequirementAssessmentReview:
    """Create the next immutable review record for one assessment.

    ``existing`` are the reviews already stored for this run; the new
    record continues that assessment's version sequence instead of
    overwriting anything. The assessment itself is passed through
    untouched, and no golden state is read or written.
    """
    if assessment.human_review_status is not HumanReviewStatus.REQUIRED:
        msg = "only an assessment requiring human review can be reviewed"
        raise ReviewValidationError(msg)
    version = 1 + max(
        (
            review.review_version
            for review in existing
            if review.assessment_id == assessment.assessment_id
        ),
        default=0,
    )
    return RequirementAssessmentReview(
        review_id=review_id_for(assessment.assessment_id, version),
        review_version=version,
        assessment_id=assessment.assessment_id,
        assessment_version=assessment.assessment_version,
        assessment_digest=assessment_digest(assessment),
        requirement_id=assessment.requirement_id,
        bid_id=assessment.bid_id,
        run_id=run_id,
        decision=decision,
        reviewer=reviewer,
        rationale=rationale,
        reviewed_at=reviewed_at,
    )


def project_reviewed_assessments(
    assessments: tuple[RequirementKnowledgeAssessment, ...],
    reviews: tuple[RequirementAssessmentReview, ...],
) -> ReviewedAssessmentProjection:
    """Combine assessments with their latest applicable reviews.

    A review applies only when its assessment identifier, schema
    version, and content digest all match the current assessment; stale
    reviews are silently *not applied* (they remain in the store as
    history). Among applicable reviews the highest ``review_version``
    wins. Assessment order is preserved.
    """
    reviewed: list[ReviewedRequirementAssessment] = []
    for assessment in assessments:
        digest = assessment_digest(assessment)
        applicable = [
            review
            for review in reviews
            if review.assessment_id == assessment.assessment_id
            and review.assessment_version == assessment.assessment_version
            and review.assessment_digest == digest
        ]
        latest = max(applicable, key=lambda review: review.review_version, default=None)
        reviewed.append(ReviewedRequirementAssessment(assessment=assessment, review=latest))
    version = assessments[0].assessment_version if assessments else "1.0.0"
    return ReviewedAssessmentProjection(
        assessment_version=version,
        reviewed=tuple(reviewed),
    )
