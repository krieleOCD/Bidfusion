"""End-to-end: synthetic RFP fixture to golden knowledge assessments.

Exercises the real chain — preflight, gate policy, DOCX parser,
rule-based requirement extraction — over the committed ``rfp-mtd``
SYNTHETIC RFP FIXTURE, then bridges the extracted requirements into the
golden pilot matcher against the synthetic golden snapshot. No network,
no model, no real data anywhere.
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
    KnowledgeStoreState,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    ClaimStatus,
    HumanReviewStatus,
    MatchStatus,
    Technology,
)
from bidfusion.schemas.common import RequirementModality
from bidfusion.schemas.extraction import RequirementExtractionResult

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def mtd_requirements() -> RequirementExtractionResult:
    """Requirements of the rfp-mtd fixture through the real parser chain."""
    canonicals = build_package_canonicals(
        SYNTHETIC_FIXTURES / "rfp-mtd", ("mtd-requirements.docx",)
    )
    return extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000021",
        created_at=NOW,
    )


def test_the_fixture_yields_the_expected_requirement_contracts(
    mtd_requirements: RequirementExtractionResult,
) -> None:
    requirements = mtd_requirements.requirements

    # eight explicit labels plus the two v0.3 modal-statement
    # submission requirements of the fixture's closing section
    assert len(requirements) == 10
    assert all(item.source.canonical_artifact_id is not None for item in requirements)
    assert all(item.source.filename == "mtd-requirements.docx" for item in requirements)
    assert requirements[0].modality is RequirementModality.MUST
    assert requirements[4].modality is RequirementModality.SHOULD


def test_end_to_end_assessment_over_the_synthetic_golden_snapshot(
    mtd_requirements: RequirementExtractionResult,
    tmp_path: Path,
) -> None:
    root = tmp_path / "golden"
    populate_synthetic_golden_store(root)
    snapshot = load_claims_snapshot(root)

    result = assess_requirements(mtd_requirements.requirements, snapshot)

    assert result.store_state is KnowledgeStoreState.AVAILABLE
    assert len(result.assessments) == 10

    by_status = [item.match_status for item in result.assessments]
    assert by_status.count(MatchStatus.MATCHED) >= 1
    assert MatchStatus.UNKNOWN in by_status or MatchStatus.GAP in by_status

    # Every assessment requires human review; nothing is confirmed.
    for item in result.assessments:
        assert item.human_review_status is HumanReviewStatus.REQUIRED
        if item.knowledge_claim_status is not None:
            assert item.knowledge_claim_status is ClaimStatus.EXTRACTED_UNVERIFIED

    sentinel = result.assessments[1]
    assert sentinel.match_status is MatchStatus.MATCHED
    assert sentinel.technology_hint is Technology.MICROSOFT_SENTINEL
    assert sentinel.matched_capability is CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT
    assert sentinel.evidence_refs

    unknown_technology = result.assessments[6]
    assert unknown_technology.match_status is MatchStatus.UNKNOWN
    assert unknown_technology.technology_hint is Technology.UNKNOWN
    assert unknown_technology.evidence_refs == ()

    negated = result.assessments[7]
    assert negated.match_status is MatchStatus.UNKNOWN
    assert negated.matched_claim_id is None
    assert negated.technology_hint is Technology.SPLUNK


def test_provenance_survives_the_whole_chain(
    mtd_requirements: RequirementExtractionResult,
    tmp_path: Path,
) -> None:
    root = tmp_path / "golden"
    populate_synthetic_golden_store(root)

    result = assess_requirements(mtd_requirements.requirements, load_claims_snapshot(root))

    matched = next(item for item in result.assessments if item.match_status is MatchStatus.MATCHED)
    # RFP side: canonical document provenance from the real parser.
    assert matched.requirement_source.filename == "mtd-requirements.docx"
    assert matched.requirement_source.locator.paragraph_id is not None
    # Golden side: evidence references into the golden snapshot.
    assert matched.evidence_refs[0].section_id.startswith("SEC-")
    assert matched.evidence_refs[0].source_version == "1.0"
