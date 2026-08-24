"""Golden matching tests for both normalization paths.

The existing golden matcher stays authoritative and local for both
paths: the LLM never searches or ranks golden evidence — its validated
normalization only produces a second ``RequirementCandidate`` that is
fed through the SAME deterministic matcher. Golden claims are never
mutated, and the deterministic path is byte-identical to what the
existing assessment service computes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import synthetic_golden_claims

from bidfusion.bid_intelligence.matching.adapter import adapt_requirement
from bidfusion.golden_dataset.contracts import MatchStatus, Technology
from bidfusion.golden_dataset.matching import match_requirement
from bidfusion.rfp_api_pilot.contracts import LlmRequirementNormalization
from bidfusion.rfp_api_pilot.golden_paths import (
    GoldenMatchComparison,
    compare_golden_matches,
)
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizedRequirement,
)
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def requirement_for(text: str) -> Requirement:
    return Requirement(
        requirement_id="REQ-000001",
        bid_id=BID_ID,
        original_text=text,
        modality=RequirementModality.MUST,
        category=RequirementCategory.TECHNICAL,
        confidence=0.9,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-001",
            filename="anonymized-rfp.docx",
            document_hash="a" * 64,
            locator=SourceLocator(paragraph_id="p-0001"),
            canonical_artifact_id="ART-20260821-000001",
        ),
        extraction=ExtractionInfo(
            method="rule",
            producer="bidfusion-rule-requirement-extractor",
            producer_version="0.1.0",
        ),
    )


def llm_result(
    *,
    technology: str = "microsoft_sentinel",
    capability: str = "microsoft_sentinel_support",
    requirement_type: str = "obligation",
    mandatory_status: str = "mandatory",
    validated: bool = True,
) -> LlmNormalizedRequirement:
    normalization = (
        LlmRequirementNormalization.model_validate(
            {
                "schema_version": "1.0.0",
                "requirement_id": "REQ-000001",
                "requirement_type": requirement_type,
                "mandatory_status": mandatory_status,
                "technology": technology,
                "capability": capability,
                "normalization_status": "normalized",
                "confidence_band": "HIGH",
                "rationale": "Test normalization.",
            }
        )
        if validated
        else None
    )
    return LlmNormalizedRequirement.model_validate(
        {
            "bid_id": BID_ID,
            "requirement_id": "REQ-000001",
            "operation": "rfp_requirement_normalization",
            "prompt_version": "1",
            "validation_status": ("VALIDATED" if validated else "GATEWAY_FAILED"),
            "normalization": normalization,
            "gateway_error_code": None if validated else "timeout",
            "normalized_at": NOW,
            "requirement_text_sha256": "b" * 64,
        }
    )


def comparison_for(text: str, llm: LlmNormalizedRequirement) -> GoldenMatchComparison:
    return compare_golden_matches(
        adapt_requirement(requirement_for(text)), llm, synthetic_golden_claims()
    )


# --- the deterministic path stays authoritative ------------------------------


def test_deterministic_path_equals_the_existing_matcher_verdict() -> None:
    text = "The service must support Microsoft Sentinel."
    adapted = adapt_requirement(requirement_for(text))
    claims = synthetic_golden_claims()
    direct = match_requirement(adapted.candidate, claims)

    comparison = compare_golden_matches(adapted, llm_result(), claims)

    assert comparison.deterministic.match_status is direct.match_status
    assert comparison.deterministic.matched_claim_id == direct.claim_id
    assert comparison.deterministic.evidence_count == len(direct.evidence_refs)


def test_golden_claims_are_never_mutated() -> None:
    claims = synthetic_golden_claims()
    snapshot = tuple(claim.model_dump_json() for claim in claims)
    compare_golden_matches(
        adapt_requirement(requirement_for("Sentinel monitoring 24/7.")), llm_result(), claims
    )
    assert tuple(claim.model_dump_json() for claim in claims) == snapshot


# --- the LLM path goes through the same matcher ------------------------------


def test_llm_capability_hint_can_reach_a_match_where_tokens_miss() -> None:
    # "round-the-clock eyes-on-glass" carries no deterministic pilot token.
    text = "Round-the-clock eyes-on-glass coverage of the security estate is expected."
    comparison = comparison_for(
        text, llm_result(technology="unknown", capability="24_7_monitoring")
    )

    assert comparison.deterministic.match_status is MatchStatus.UNKNOWN
    assert comparison.llm is not None
    assert comparison.llm.match_status is MatchStatus.MATCHED
    assert comparison.llm.matched_claim_id is not None
    assert comparison.llm.evidence_count >= 1
    assert comparison.match_agreement is False


def test_agreement_when_both_paths_match() -> None:
    comparison = comparison_for("The service must support Microsoft Sentinel.", llm_result())
    assert comparison.deterministic.match_status is MatchStatus.MATCHED
    assert comparison.llm is not None
    assert comparison.llm.match_status is MatchStatus.MATCHED
    assert comparison.match_agreement is True


def test_llm_exclusion_reading_is_never_matched_positively() -> None:
    comparison = comparison_for(
        "The service must support Microsoft Sentinel.",
        llm_result(requirement_type="exclusion", mandatory_status="excluded"),
    )
    assert comparison.llm is not None
    assert comparison.llm.match_status is MatchStatus.UNKNOWN
    assert comparison.llm.matched_claim_id is None
    assert comparison.llm.evidence_count == 0


def test_missing_llm_result_leaves_the_llm_path_empty() -> None:
    comparison = comparison_for(
        "The service must support Microsoft Sentinel.", llm_result(validated=False)
    )
    assert comparison.llm is None
    assert comparison.match_agreement is None


def test_llm_technology_hint_is_carried_on_the_llm_path() -> None:
    comparison = comparison_for("The service must support Microsoft Sentinel.", llm_result())
    assert comparison.llm is not None
    assert comparison.llm.technology is Technology.MICROSOFT_SENTINEL
    assert comparison.deterministic.technology is Technology.MICROSOFT_SENTINEL
