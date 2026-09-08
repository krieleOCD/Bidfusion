"""End-to-end: synthetic RFP through assessment, human review, projection.

The full governed chain over the committed SYNTHETIC RFP FIXTURE — real
preflight, gate decision, DOCX parser, extraction, deterministic
assessment — followed by human review decisions, store persistence, and
the reviewed projection. Golden data is the synthetic snapshot; nothing
golden changes state at any point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import (
    SYNTHETIC_FIXTURES,
    build_package_canonicals,
    populate_synthetic_golden_store,
)

from bidfusion.bid_intelligence.matching import (
    KnowledgeAssessmentResult,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.review import (
    ReviewDecision,
    ReviewState,
    RunReviewStore,
    project_reviewed_assessments,
    record_requirement_assessment_review,
)
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.golden_dataset.contracts import ClaimStatus, MatchStatus
from bidfusion.golden_dataset.store import GoldenKnowledgeStore

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260821-0001"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def assessed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, KnowledgeAssessmentResult]:
    """The fixture package assessed against the synthetic golden snapshot."""
    golden_root = tmp_path_factory.mktemp("golden") / "store"
    populate_synthetic_golden_store(golden_root)
    canonicals = build_package_canonicals(
        SYNTHETIC_FIXTURES / "rfp-mtd", ("mtd-requirements.docx",)
    )
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260821-000021",
        created_at=NOW,
    )
    result = assess_requirements(requirements.requirements, load_claims_snapshot(golden_root))
    return golden_root, result


def test_review_to_reviewed_projection_end_to_end(
    assessed: tuple[Path, KnowledgeAssessmentResult], tmp_path: Path
) -> None:
    golden_root, result = assessed
    claims_before = (golden_root / "claims.json").read_bytes()
    assessments = result.assessments
    matched = [item for item in assessments if item.match_status is MatchStatus.MATCHED]
    unknown = [item for item in assessments if item.match_status is MatchStatus.UNKNOWN]
    assert len(matched) >= 2 and len(unknown) >= 1

    store = RunReviewStore(tmp_path / "reviews")
    plan = (
        (matched[0], ReviewDecision.CONFIRMED, "Sentinel coverage fits this bid."),
        (matched[1], ReviewDecision.REJECTED, None),
        (unknown[0], ReviewDecision.NEEDS_CLARIFICATION, None),
    )
    for assessment, decision, rationale in plan:
        review = record_requirement_assessment_review(
            assessment,
            decision=decision,
            reviewer="Alex Reviewer",
            rationale=rationale,
            reviewed_at=NOW,
            run_id=RUN_ID,
            existing=store.read_reviews(),
        )
        store.append_review(review)

    projection = project_reviewed_assessments(assessments, store.read_reviews())

    by_id = {item.assessment.assessment_id: item for item in projection.reviewed}
    confirmed = by_id[matched[0].assessment_id]
    rejected = by_id[matched[1].assessment_id]
    clarify = by_id[unknown[0].assessment_id]

    # Machine and human dimensions stay separate and visible.
    assert confirmed.assessment.match_status is MatchStatus.MATCHED
    assert confirmed.review_state is ReviewState.CONFIRMED
    assert rejected.assessment.match_status is MatchStatus.MATCHED
    assert rejected.review_state is ReviewState.REJECTED
    assert clarify.assessment.match_status is MatchStatus.UNKNOWN
    assert clarify.review_state is ReviewState.NEEDS_CLARIFICATION

    # Reviews bind the exact assessment reviewed.
    assert confirmed.review is not None
    assert confirmed.review.assessment_id == matched[0].assessment_id
    assert confirmed.review.assessment_version == matched[0].assessment_version

    # Provenance survives untouched on both sides.
    assert confirmed.assessment.requirement_source.filename == "mtd-requirements.docx"
    assert confirmed.assessment.evidence_refs[0].section_id.startswith("SEC-")

    # Nothing golden changed; the assessments themselves are unchanged.
    assert (golden_root / "claims.json").read_bytes() == claims_before
    for claim in GoldenKnowledgeStore(golden_root).read_claims():
        assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED
    assert confirmed.assessment == matched[0]

    # Every unreviewed assessment stays pending; totals add up.
    counts = projection.counts
    assert counts[ReviewState.CONFIRMED] == 1
    assert counts[ReviewState.REJECTED] == 1
    assert counts[ReviewState.NEEDS_CLARIFICATION] == 1
    assert counts[ReviewState.PENDING] == len(assessments) - 3
