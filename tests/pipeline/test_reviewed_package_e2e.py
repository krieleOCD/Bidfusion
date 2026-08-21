"""End-to-end: synthetic RFP through reviews into versioned reviewed packages.

The full governed chain over the committed SYNTHETIC RFP FIXTURE — real
preflight, gate decision, DOCX parser, extraction, deterministic
assessment — followed by human reviews, Reviewed Working Package v1,
another review, package v2, and the fully verified persisted load.
Golden data is the synthetic snapshot; nothing golden changes state and
no earlier package version changes at any point.
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
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.review import (
    PackageReviewState,
    ReviewDecision,
    ReviewedPackageStore,
    ReviewState,
    RunReviewStore,
    build_reviewed_working_package,
    record_requirement_assessment_review,
)
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.golden_dataset.contracts import ClaimStatus, MatchStatus
from bidfusion.golden_dataset.store import GoldenKnowledgeStore
from bidfusion.schemas.extraction import RequirementExtractionResult

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260821-0001"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def chain(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, RequirementExtractionResult]:
    """The fixture package extracted for assessment against synthetic golden."""
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
    return golden_root, requirements


def test_reviewed_packages_version_through_the_full_synthetic_loop(
    chain: tuple[Path, RequirementExtractionResult], tmp_path: Path
) -> None:
    golden_root, requirements = chain
    claims_before = (golden_root / "claims.json").read_bytes()
    assessments = assess_requirements(
        requirements.requirements, load_claims_snapshot(golden_root)
    ).assessments
    matched = [item for item in assessments if item.match_status is MatchStatus.MATCHED]
    unknown = [item for item in assessments if item.match_status is MatchStatus.UNKNOWN]
    assert len(matched) >= 3 and len(unknown) >= 1

    # Three human reviews out of eight assessments.
    review_store = RunReviewStore(tmp_path / "reviews")
    plan = (
        (matched[0], ReviewDecision.CONFIRMED, "Sentinel coverage fits this bid."),
        (matched[1], ReviewDecision.REJECTED, None),
        (unknown[0], ReviewDecision.NEEDS_CLARIFICATION, None),
    )
    for assessment, decision, rationale in plan:
        review_store.append_review(
            record_requirement_assessment_review(
                assessment,
                decision=decision,
                reviewer="Alex Reviewer",
                rationale=rationale,
                reviewed_at=NOW,
                run_id=RUN_ID,
                existing=review_store.read_reviews(),
            )
        )

    # Package v1: three reviewed, five pending — honestly incomplete.
    package_store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    v1 = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=review_store.read_reviews(),
        package_version=package_store.next_version(),
        artifact_id="ART-20260821-000031",
        created_at=NOW,
    )
    package_store.append_package(v1)
    v1_payload = (
        tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.payload.json"
    ).read_bytes()
    assert v1.package_version == 1
    assert v1.package_review_state is PackageReviewState.REVIEW_INCOMPLETE
    assert v1.summary.total_requirements == len(assessments)
    assert v1.summary.reviewed == 3
    assert v1.summary.pending == len(assessments) - 3

    # One more review arrives; v2 captures it, v1 stays intact.
    review_store.append_review(
        record_requirement_assessment_review(
            matched[2],
            decision=ReviewDecision.CONFIRMED,
            reviewer="Kim Reviewer",
            rationale=None,
            reviewed_at=LATER,
            run_id=RUN_ID,
            existing=review_store.read_reviews(),
        )
    )
    v2 = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=review_store.read_reviews(),
        package_version=package_store.next_version(),
        artifact_id="ART-20260821-000032",
        created_at=LATER,
    )
    package_store.append_package(v2)

    loaded_v1, loaded_v2 = package_store.read_packages()
    assert loaded_v1 == v1
    assert loaded_v2 == v2
    assert v1 != v2
    assert v2.summary.reviewed == 4
    assert v2.summary.pending == len(assessments) - 4
    assert (
        tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.payload.json"
    ).read_bytes() == v1_payload

    # The three trust layers survive persistence separately.
    by_id = {entry.machine.assessment_id: entry for entry in loaded_v2.requirements}
    confirmed = by_id[matched[0].assessment_id]
    rejected = by_id[matched[1].assessment_id]
    clarify = by_id[unknown[0].assessment_id]
    assert confirmed.machine.match_status is MatchStatus.MATCHED
    assert confirmed.review_state is ReviewState.CONFIRMED
    assert rejected.machine.match_status is MatchStatus.MATCHED
    assert rejected.review_state is ReviewState.REJECTED
    assert rejected.golden.claim_status is ClaimStatus.EXTRACTED_UNVERIFIED
    assert clarify.machine.match_status is MatchStatus.UNKNOWN
    assert clarify.review_state is ReviewState.NEEDS_CLARIFICATION

    # RFP provenance and golden evidence provenance are both intact.
    assert confirmed.rfp.source.filename == "mtd-requirements.docx"
    # The RFP layer keeps the *original* text (identifier prefix included);
    # the machine layer worked on the normalized form.
    assert matched[0].requirement_text in confirmed.rfp.text
    assert confirmed.golden.evidence_refs[0].section_id.startswith("SEC-")
    assert loaded_v2.source_requirements.artifact_id == requirements.artifact.artifact_id

    # The human review layer is carried verbatim, revision included.
    assert confirmed.human_review is not None
    assert confirmed.human_review.reviewer == "Alex Reviewer"
    assert confirmed.human_review.rationale == "Sentinel coverage fits this bid."
    assert by_id[matched[2].assessment_id].human_review is not None
    v1_entry = {entry.machine.assessment_id: entry for entry in loaded_v1.requirements}[
        matched[2].assessment_id
    ]
    assert v1_entry.human_review is None

    # Nothing golden changed; nothing upstream changed.
    assert (golden_root / "claims.json").read_bytes() == claims_before
    for claim in GoldenKnowledgeStore(golden_root).read_claims():
        assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED
