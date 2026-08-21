"""Contract invariants of the bid-side requirement assessment review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pydantic
import pytest

from bidfusion.bid_intelligence.matching import (
    ClaimsSnapshot,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    assess_requirements,
)
from bidfusion.bid_intelligence.review import (
    MAX_RATIONALE_LENGTH,
    MAX_REVIEWER_LENGTH,
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewedRequirementAssessment,
    ReviewState,
    assessment_digest,
    review_id_for,
)
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _assessment() -> RequirementKnowledgeAssessment:
    requirement = Requirement(
        requirement_id="REQ-000001",
        bid_id=BID_ID,
        original_text="The service MUST support Microsoft Sentinel.",
        modality=RequirementModality.MUST,
        category=RequirementCategory.TECHNICAL,
        confidence=0.9,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-001",
            filename="mtd-requirements.docx",
            document_hash="a" * 64,
            locator=SourceLocator(paragraph_id="p-1"),
            canonical_artifact_id="ART-20260804-000011",
        ),
        extraction=ExtractionInfo(method="rule", producer="x", producer_version="0.1.0"),
    )
    result = assess_requirements(
        (requirement,), ClaimsSnapshot(state=KnowledgeStoreState.UNAVAILABLE)
    )
    return result.assessments[0]


def _review_fields(assessment: RequirementKnowledgeAssessment) -> dict[str, Any]:
    return {
        "review_id": review_id_for(assessment.assessment_id, 1),
        "review_version": 1,
        "assessment_id": assessment.assessment_id,
        "assessment_version": assessment.assessment_version,
        "assessment_digest": assessment_digest(assessment),
        "requirement_id": "REQ-000001",
        "bid_id": BID_ID,
        "run_id": "RUN-20260821-0001",
        "decision": ReviewDecision.CONFIRMED,
        "reviewer": "Alex Reviewer",
        "rationale": "Looks right for this bid.",
        "reviewed_at": NOW,
    }


def test_a_valid_review_constructs_and_is_frozen() -> None:
    assessment = _assessment()
    review = RequirementAssessmentReview(**_review_fields(assessment))

    assert review.decision is ReviewDecision.CONFIRMED
    assert review.review_version == 1
    with pytest.raises(pydantic.ValidationError):
        review.decision = ReviewDecision.REJECTED


@pytest.mark.parametrize(
    ("override", "label"),
    [
        ({"decision": "APPROVED"}, "invalid decision"),
        ({"reviewer": ""}, "empty reviewer"),
        ({"reviewer": "   "}, "blank reviewer"),
        ({"reviewer": "R" * (MAX_REVIEWER_LENGTH + 1)}, "oversized reviewer"),
        ({"rationale": "r" * (MAX_RATIONALE_LENGTH + 1)}, "oversized rationale"),
        ({"reviewed_at": datetime(2026, 8, 21, 12, 0)}, "naive timestamp"),
        ({"assessment_version": "not-a-version"}, "malformed assessment version"),
        ({"assessment_digest": "zz"}, "malformed digest"),
        ({"review_id": "REV-aaaaaaaaaaaa"}, "underived review id"),
        ({"review_version": 0}, "zero review version"),
        ({"extra_field": "x"}, "undeclared field"),
    ],
)
def test_malformed_reviews_fail_closed(override: dict[str, Any], label: str) -> None:
    fields = {**_review_fields(_assessment()), **override}
    with pytest.raises(pydantic.ValidationError):
        RequirementAssessmentReview(**fields)


def test_review_id_is_deterministically_derived() -> None:
    assessment = _assessment()
    first = review_id_for(assessment.assessment_id, 1)
    second = review_id_for(assessment.assessment_id, 2)

    assert first == review_id_for(assessment.assessment_id, 1)
    assert first != second
    assert first.startswith("REV-")


def test_projection_rejects_a_review_of_a_different_assessment() -> None:
    assessment = _assessment()
    review = RequirementAssessmentReview(**_review_fields(assessment))

    for override in (
        {"assessment_id": "RKA-ffffffffffff", "review_id": review_id_for("RKA-ffffffffffff", 1)},
        {"assessment_version": "9.9.9"},
        {"assessment_digest": "b" * 64},
    ):
        stale = review.model_copy(update=override)
        with pytest.raises(pydantic.ValidationError):
            ReviewedRequirementAssessment(assessment=assessment, review=stale)


def test_projection_accepts_the_exact_matching_review_and_maps_states() -> None:
    assessment = _assessment()
    review = RequirementAssessmentReview(**_review_fields(assessment))

    reviewed = ReviewedRequirementAssessment(assessment=assessment, review=review)
    assert reviewed.review_state is ReviewState.CONFIRMED

    pending = ReviewedRequirementAssessment(assessment=assessment, review=None)
    assert pending.review_state is ReviewState.PENDING


def test_the_digest_binds_the_full_assessment_content() -> None:
    assessment = _assessment()
    changed = assessment.model_copy(update={"rationale": "different rationale text"})

    assert assessment_digest(assessment) != assessment_digest(changed)
