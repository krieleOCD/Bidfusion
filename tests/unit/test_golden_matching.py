"""Deterministic keyword/taxonomy matching tests — synthetic inputs only."""

from __future__ import annotations

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ClaimStatus,
    ConfidenceBand,
    EvidenceReference,
    HumanReviewStatus,
    KnowledgeSourceLocator,
    MatchStatus,
    RequirementCandidate,
    ServiceFamily,
    Technology,
)
from bidfusion.golden_dataset.matching import (
    SYNTHETIC_DEMO_REQUIREMENTS,
    match_requirement,
)


def _claim(
    capability: CapabilityCategory,
    technology: Technology,
    *,
    status: ClaimStatus = ClaimStatus.EXTRACTED_UNVERIFIED,
) -> CapabilityClaim:
    claim = CapabilityClaim(
        claim_id="GCL-00000000000a",
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=technology,
        capability=capability,
        statement="Synthetic claim statement.",
        evidence_refs=(
            EvidenceReference(
                source_id="GKS-00000000000a",
                section_id="SEC-0001",
                locator=KnowledgeSourceLocator(paragraph_index=1),
                source_version="1.0",
            ),
        ),
        confidence_band=ConfidenceBand.MEDIUM,
    )
    if status is not ClaimStatus.EXTRACTED_UNVERIFIED:
        claim = claim.model_copy(update={"status": status})
    return claim


def _requirement(text: str) -> RequirementCandidate:
    return RequirementCandidate(requirement_id="DEMO-REQ-999", text=text)


class TestStatuses:
    def test_exact_technology_match(self) -> None:
        claims = (
            _claim(CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT, Technology.MICROSOFT_SENTINEL),
        )
        result = match_requirement(
            _requirement("The service must support Microsoft Sentinel."), claims
        )
        assert result.match_status is MatchStatus.MATCHED
        assert result.claim_id == claims[0].claim_id
        assert result.evidence_refs == claims[0].evidence_refs

    def test_partial_match_when_one_aspect_is_uncovered(self) -> None:
        claims = (
            _claim(CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT, Technology.MICROSOFT_SENTINEL),
        )
        result = match_requirement(
            _requirement("24/7 monitoring of Microsoft Sentinel is required."), claims
        )
        assert result.match_status is MatchStatus.PARTIAL

    def test_unknown_when_no_aspect_is_recognized(self) -> None:
        result = match_requirement(
            _requirement("The bidder shall provide a synthetic unrelated capability."), ()
        )
        assert result.match_status is MatchStatus.UNKNOWN
        assert result.claim_id is None

    def test_gap_when_aspect_recognized_but_no_claim_exists(self) -> None:
        result = match_requirement(
            _requirement("The service must support Vectra."),
            (_claim(CapabilityCategory.SPLUNK_SUPPORT, Technology.SPLUNK),),
        )
        assert result.match_status is MatchStatus.GAP

    def test_evidence_required_when_only_rejected_claims_cover_the_aspect(self) -> None:
        rejected = _claim(
            CapabilityCategory.VECTRA_SUPPORT,
            Technology.VECTRA,
            status=ClaimStatus.SUPERSEDED,
        )
        result = match_requirement(_requirement("The service must support Vectra."), (rejected,))
        assert result.match_status is MatchStatus.EVIDENCE_REQUIRED

    def test_matching_is_deterministic(self) -> None:
        claims = (
            _claim(CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT, Technology.MICROSOFT_SENTINEL),
        )
        requirement = _requirement("The service must support Microsoft Sentinel.")
        assert match_requirement(requirement, claims) == match_requirement(requirement, claims)

    def test_every_match_requires_human_review(self) -> None:
        result = match_requirement(_requirement("Splunk support required."), ())
        assert result.human_review_status is HumanReviewStatus.REQUIRED


class TestDemoRequirements:
    def test_demo_requirements_are_five_and_marked_synthetic(self) -> None:
        assert len(SYNTHETIC_DEMO_REQUIREMENTS) == 5
        assert all(
            requirement.requirement_id.startswith("DEMO-REQ-")
            for requirement in SYNTHETIC_DEMO_REQUIREMENTS
        )
