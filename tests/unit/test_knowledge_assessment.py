"""Assessment service tests: statuses, failure modes, and trust semantics.

All golden data here is the synthetic snapshot from ``conftest``. The
central invariants: every assessment requires human review, an
unverified claim never surfaces as confirmed, and an absent or damaged
store is reported as *not evaluated* — never as a capability gap.
"""

from __future__ import annotations

from pathlib import Path

from conftest import (
    GOLDEN_SOURCE_ID,
    populate_synthetic_golden_store,
    synthetic_golden_claims,
)

from bidfusion.bid_intelligence.matching import (
    KnowledgeStoreState,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    ClaimStatus,
    HumanReviewStatus,
    MatchStatus,
    Technology,
    reject_claim,
)
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"


def _requirement(
    text: str,
    *,
    requirement_id: str = "REQ-000001",
    modality: RequirementModality = RequirementModality.MUST,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        bid_id=BID_ID,
        original_text=text,
        modality=modality,
        category=RequirementCategory.TECHNICAL,
        confidence=0.9,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-001",
            filename="mtd-requirements.docx",
            document_hash="a" * 64,
            locator=SourceLocator(paragraph_id="p-0001"),
            canonical_artifact_id="ART-20260804-000011",
        ),
        extraction=ExtractionInfo(
            method="rule",
            producer="bidfusion-rule-requirement-extractor",
            producer_version="0.1.0",
        ),
    )


# --- verdicts over an available snapshot -------------------------------------


def test_sentinel_requirement_is_a_matched_candidate_with_evidence(tmp_path: Path) -> None:
    snapshot = load_claims_snapshot(_store(tmp_path))
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    )

    assessment = result.assessments[0]
    assert assessment.match_status is MatchStatus.MATCHED
    assert assessment.matched_claim_id is not None
    assert assessment.matched_capability is CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT
    assert assessment.knowledge_claim_status is ClaimStatus.EXTRACTED_UNVERIFIED
    assert assessment.evidence_refs
    assert assessment.evidence_refs[0].source_id == GOLDEN_SOURCE_ID
    assert assessment.human_review_status is HumanReviewStatus.REQUIRED


def test_partial_match_when_only_one_aspect_is_claimed(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    populate_synthetic_golden_store(
        root,
        claims=synthetic_golden_claims((CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,)),
    )
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel and Vectra sensors."),),
        load_claims_snapshot(root),
    )

    assert result.assessments[0].match_status is MatchStatus.PARTIAL
    assert result.assessments[0].evidence_refs


def test_unrecognized_text_is_unknown_not_gap(tmp_path: Path) -> None:
    result = assess_requirements(
        (_requirement("The platform MUST integrate with the QuantumTrace AlphaSIEM appliance."),),
        load_claims_snapshot(_store(tmp_path)),
    )

    assessment = result.assessments[0]
    assert assessment.match_status is MatchStatus.UNKNOWN
    assert assessment.matched_claim_id is None
    assert assessment.evidence_refs == ()


def test_recognized_but_unclaimed_capability_is_a_gap(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    populate_synthetic_golden_store(
        root,
        claims=synthetic_golden_claims((CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,)),
    )
    result = assess_requirements(
        (_requirement("The provider MUST support Vectra network sensors."),),
        load_claims_snapshot(root),
    )

    assert result.assessments[0].match_status is MatchStatus.GAP
    assert result.assessments[0].matched_claim_id is None


def test_only_rejected_claims_yield_evidence_required(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    claims = tuple(
        reject_claim(claim, reviewer="Synthetic Reviewer")
        for claim in synthetic_golden_claims((CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,))
    )
    populate_synthetic_golden_store(root, claims=claims)
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),),
        load_claims_snapshot(root),
    )

    assert result.assessments[0].match_status is MatchStatus.EVIDENCE_REQUIRED


def test_no_negative_or_excluded_phrasing_ever_matches_positively(tmp_path: Path) -> None:
    """H-1: even with every pilot capability claimed, clearly negative or
    excluding requirement language must never yield MATCHED or PARTIAL,
    a claim reference, or evidence — it fails toward UNKNOWN and review."""
    root = tmp_path / "golden"
    populate_synthetic_golden_store(root, claims=synthetic_golden_claims(tuple(CapabilityCategory)))
    snapshot = load_claims_snapshot(root)

    phrasings = (
        "Splunk support is not required.",
        "Splunk support is not in scope.",
        "Splunk support is excluded.",
        "Isolation is excluded for this lot.",
        "Splunk support is not part of this tender.",
        "Splunk support will not be needed.",
        "We do not require Splunk support.",
        "The bidder does not require Splunk support.",
        "Splunk support is not a requirement.",
        "No Splunk support is required.",
        "Sentinel is required but isolation is excluded.",
        "Sentinel is required; Splunk is excluded.",
        "The service excludes Splunk support.",
        "Splunk support is outside the scope.",
        "Splunk support is out-of-scope.",
    )
    requirements = tuple(
        _requirement(text, requirement_id=f"REQ-{index:06d}", modality=RequirementModality.UNKNOWN)
        for index, text in enumerate(phrasings, start=1)
    )

    result = assess_requirements(requirements, snapshot)

    for assessment, text in zip(result.assessments, phrasings, strict=True):
        assert assessment.match_status is MatchStatus.UNKNOWN, text
        assert assessment.matched_claim_id is None, text
        assert assessment.evidence_refs == (), text
        assert assessment.human_review_status is HumanReviewStatus.REQUIRED, text


def test_negated_requirement_is_never_a_positive_candidate(tmp_path: Path) -> None:
    result = assess_requirements(
        (
            _requirement(
                "Splunk support is not required and is excluded from scope.",
                modality=RequirementModality.UNKNOWN,
            ),
        ),
        load_claims_snapshot(_store(tmp_path)),
    )

    assessment = result.assessments[0]
    assert assessment.match_status is MatchStatus.UNKNOWN
    assert assessment.matched_claim_id is None
    assert assessment.evidence_refs == ()
    assert assessment.technology_hint is Technology.SPLUNK


# --- store failure modes ------------------------------------------------------


def test_missing_store_is_unavailable_and_produces_no_verdict(tmp_path: Path) -> None:
    snapshot = load_claims_snapshot(tmp_path / "does-not-exist")
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    )

    assert result.store_state is KnowledgeStoreState.UNAVAILABLE
    assert result.claim_count == 0
    assessment = result.assessments[0]
    assert assessment.match_status is None
    assert assessment.human_review_status is HumanReviewStatus.REQUIRED
    assert "not a capability gap" in result.store_note


def test_corrupt_claims_file_is_unreadable_not_gap(tmp_path: Path) -> None:
    root = _store(tmp_path)
    (root / "claims.json").write_text("{ this is not json", encoding="utf-8")

    snapshot = load_claims_snapshot(root)
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    )

    assert result.store_state is KnowledgeStoreState.UNREADABLE
    assert result.assessments[0].match_status is None


def test_stale_evidence_fails_the_integrity_check_and_is_not_used(tmp_path: Path) -> None:
    root = _store(tmp_path)
    for document in sorted((root / "documents").glob("GKD-*.json")):
        document.unlink()

    snapshot = load_claims_snapshot(root)
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    )

    assert result.store_state is KnowledgeStoreState.INTEGRITY_FAILED
    assert result.assessments[0].match_status is None


def test_store_without_claims_reports_no_claims_not_gap(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    store = populate_synthetic_golden_store(root)
    (root / "claims.json").unlink()
    assert store.read_claims() == ()

    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),),
        load_claims_snapshot(root),
    )

    assert result.store_state is KnowledgeStoreState.NO_CLAIMS
    assert result.assessments[0].match_status is None


# --- provenance and trust preservation ---------------------------------------


def test_rfp_and_golden_provenance_are_both_preserved_and_separate(tmp_path: Path) -> None:
    requirement = _requirement("The service MUST support Microsoft Sentinel.")
    result = assess_requirements((requirement,), load_claims_snapshot(_store(tmp_path)))

    assessment = result.assessments[0]
    assert assessment.requirement_source == requirement.source
    assert assessment.requirement_source.locator.paragraph_id == "p-0001"
    assert assessment.evidence_refs[0].section_id.startswith("SEC-")
    assert assessment.evidence_refs[0].source_version == "1.0"


def test_every_assessment_requires_human_review(tmp_path: Path) -> None:
    requirements = (
        _requirement("The service MUST support Microsoft Sentinel.", requirement_id="REQ-000001"),
        _requirement("QuantumTrace AlphaSIEM only.", requirement_id="REQ-000002"),
        _requirement(
            "Splunk support is not required.",
            requirement_id="REQ-000003",
            modality=RequirementModality.UNKNOWN,
        ),
    )
    result = assess_requirements(requirements, load_claims_snapshot(_store(tmp_path)))

    assert len(result.assessments) == 3
    assert all(
        item.human_review_status is HumanReviewStatus.REQUIRED for item in result.assessments
    )


def test_an_unverified_claim_never_surfaces_as_confirmed(tmp_path: Path) -> None:
    root = _store(tmp_path)
    snapshot = load_claims_snapshot(root)
    result = assess_requirements(
        (_requirement("The service MUST support Microsoft Sentinel."),), snapshot
    )

    assert result.assessments[0].knowledge_claim_status is ClaimStatus.EXTRACTED_UNVERIFIED
    # The golden store is untouched: the stored claims keep their status.
    for claim in snapshot.claims:
        assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED


def test_assessment_is_deterministic_across_repeats(tmp_path: Path) -> None:
    requirements = (
        _requirement("The service MUST support Microsoft Sentinel.", requirement_id="REQ-000001"),
        _requirement("24x7 monitoring is required.", requirement_id="REQ-000002"),
    )
    snapshot = load_claims_snapshot(_store(tmp_path))

    first = assess_requirements(requirements, snapshot)
    second = assess_requirements(requirements, snapshot)

    assert first == second
    assert first.assessments[0].assessment_id.startswith("RKA-")


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "golden"
    if not root.is_dir():
        populate_synthetic_golden_store(root)
    return root
