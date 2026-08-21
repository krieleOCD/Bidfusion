"""Review service and projection: versioning, staleness, golden separation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from conftest import populate_synthetic_golden_store, synthetic_golden_claims

from bidfusion.bid_intelligence.matching import (
    RequirementKnowledgeAssessment,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.review import (
    ReviewDecision,
    ReviewState,
    project_reviewed_assessments,
    record_requirement_assessment_review,
)
from bidfusion.golden_dataset.contracts import CapabilityCategory, ClaimStatus
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260821-0001"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _requirement(text: str, requirement_id: str = "REQ-000001") -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        bid_id=BID_ID,
        original_text=text,
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


def _assessment(tmp_path: Path, text: str) -> RequirementKnowledgeAssessment:
    root = tmp_path / "golden"
    if not root.is_dir():
        populate_synthetic_golden_store(root)
    result = assess_requirements((_requirement(text),), load_claims_snapshot(root))
    return result.assessments[0]


def test_each_decision_produces_an_attributable_immutable_record(tmp_path: Path) -> None:
    assessment = _assessment(tmp_path, "The service MUST support Microsoft Sentinel.")
    for decision in (
        ReviewDecision.CONFIRMED,
        ReviewDecision.REJECTED,
        ReviewDecision.NEEDS_CLARIFICATION,
    ):
        review = record_requirement_assessment_review(
            assessment,
            decision=decision,
            reviewer="Alex Reviewer",
            rationale=None,
            reviewed_at=NOW,
            run_id=RUN_ID,
        )
        assert review.decision is decision
        assert review.reviewer == "Alex Reviewer"
        assert review.assessment_id == assessment.assessment_id
        assert review.assessment_version == assessment.assessment_version
        assert review.run_id == RUN_ID
        assert review.review_version == 1


def test_reviewing_never_mutates_the_assessment_or_the_golden_claims(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    populate_synthetic_golden_store(root)
    snapshot = load_claims_snapshot(root)
    claims_before = (root / "claims.json").read_bytes()
    assessment = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    ).assessments[0]
    serialized_before = assessment.model_dump_json()

    record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.CONFIRMED,
        reviewer="Alex Reviewer",
        rationale="Fine for this bid.",
        reviewed_at=NOW,
        run_id=RUN_ID,
    )

    assert assessment.model_dump_json() == serialized_before
    assert (root / "claims.json").read_bytes() == claims_before
    assert all(claim.status is ClaimStatus.EXTRACTED_UNVERIFIED for claim in snapshot.claims)


def test_review_versions_progress_and_never_overwrite(tmp_path: Path) -> None:
    assessment = _assessment(tmp_path, "The service MUST support Microsoft Sentinel.")
    first = record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.NEEDS_CLARIFICATION,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
    )
    second = record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.CONFIRMED,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
        existing=(first,),
    )

    assert (first.review_version, second.review_version) == (1, 2)
    assert first.review_id != second.review_id
    assert first.decision is ReviewDecision.NEEDS_CLARIFICATION


def test_projection_applies_the_latest_review_and_keeps_both_dimensions(
    tmp_path: Path,
) -> None:
    assessment = _assessment(tmp_path, "The service MUST support Microsoft Sentinel.")
    first = record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.NEEDS_CLARIFICATION,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
    )
    second = record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.REJECTED,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
        existing=(first,),
    )

    projection = project_reviewed_assessments((assessment,), (first, second))
    reviewed = projection.reviewed[0]

    assert reviewed.review_state is ReviewState.REJECTED
    assert reviewed.assessment.match_status is not None  # candidate dimension intact
    assert reviewed.review is not None and reviewed.review.review_version == 2
    assert projection.counts[ReviewState.REJECTED] == 1


def test_a_stale_review_is_never_applied_to_a_changed_assessment(tmp_path: Path) -> None:
    """Assessment v1 reviewed; the knowledge snapshot changes; the same
    requirement now yields a different assessment — the old review must
    not surface on it."""
    root = tmp_path / "golden"
    populate_synthetic_golden_store(root)
    requirement = _requirement("The service MUST support Microsoft Sentinel.")
    original = assess_requirements((requirement,), load_claims_snapshot(root)).assessments[0]
    review = record_requirement_assessment_review(
        original,
        decision=ReviewDecision.CONFIRMED,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
    )

    changed_root = tmp_path / "golden-changed"
    populate_synthetic_golden_store(
        changed_root,
        claims=synthetic_golden_claims((CapabilityCategory.VECTRA_SUPPORT,)),
    )
    changed = assess_requirements((requirement,), load_claims_snapshot(changed_root)).assessments[0]
    assert changed.assessment_id == original.assessment_id  # same content identity
    assert changed.match_status is not original.match_status

    projection = project_reviewed_assessments((changed,), (review,))
    assert projection.reviewed[0].review is None
    assert projection.reviewed[0].review_state is ReviewState.PENDING


def test_unreviewed_assessments_project_as_pending(tmp_path: Path) -> None:
    assessment = _assessment(tmp_path, "The service MUST support Microsoft Sentinel.")

    projection = project_reviewed_assessments((assessment,), ())

    assert projection.reviewed[0].review is None
    assert projection.counts[ReviewState.PENDING] == 1
