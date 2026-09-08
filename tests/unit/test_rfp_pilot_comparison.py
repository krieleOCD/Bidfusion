"""Comparison tests: deterministic vs. LLM normalization, no automatic winner.

``compare_normalizations`` only states where the two methods agree or
disagree; it never declares either method correct. Its rules are fixed:
one-sided unknowns surface as DETERMINISTIC_UNKNOWN / LLM_UNKNOWN, a
missing LLM result is NOT_EVALUATED, and dimension-level disagreement is
made visible through closed comparison flags.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bidfusion.bid_intelligence.matching.adapter import adapt_requirement
from bidfusion.golden_dataset.contracts import Technology
from bidfusion.rfp_api_pilot.comparison import (
    ComparisonFlag,
    HumanEvaluationStatus,
    NormalizationAgreement,
    RequirementNormalizationComparison,
    compare_normalizations,
)
from bidfusion.rfp_api_pilot.contracts import LlmRequirementNormalization
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
    capability: str = "24_7_monitoring",
    requirement_type: str = "obligation",
    mandatory_status: str = "mandatory",
    exclusions: tuple[str, ...] = (),
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
                "exclusions": list(exclusions),
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


def compare(text: str, llm: LlmNormalizedRequirement) -> RequirementNormalizationComparison:
    return compare_normalizations(adapt_requirement(requirement_for(text)), llm)


# --- agreement ---------------------------------------------------------------


def test_full_agreement_on_a_sentinel_obligation() -> None:
    comparison = compare(
        "24/7 monitoring for Microsoft Sentinel is required.",
        llm_result(),
    )
    assert comparison.agreement is NormalizationAgreement.AGREE
    assert comparison.flags == ()
    assert comparison.deterministic_technology is Technology.MICROSOFT_SENTINEL
    assert comparison.llm_technology is Technology.MICROSOFT_SENTINEL


def test_technology_disagreement_is_partial_and_flagged() -> None:
    comparison = compare(
        "24/7 monitoring for Microsoft Sentinel is required.",
        llm_result(technology="splunk"),
    )
    assert comparison.agreement is NormalizationAgreement.PARTIAL_AGREEMENT
    assert ComparisonFlag.TECHNOLOGY_MISMATCH in comparison.flags


def test_negation_disagreement_is_flagged() -> None:
    comparison = compare(
        "Sentinel monitoring is not required and remains out of scope.",
        llm_result(),  # LLM (wrongly) reads a positive obligation
    )
    assert comparison.agreement is NormalizationAgreement.PARTIAL_AGREEMENT
    assert ComparisonFlag.NEGATION_MISMATCH in comparison.flags
    assert comparison.deterministic_negated is True
    assert comparison.llm_excluded is False


def test_total_disagreement_across_all_dimensions() -> None:
    comparison = compare(
        "Sentinel monitoring is not required and remains out of scope.",
        llm_result(technology="splunk", capability="splunk_support"),
    )
    assert comparison.agreement is NormalizationAgreement.DISAGREE
    assert set(comparison.flags) == {
        ComparisonFlag.TECHNOLOGY_MISMATCH,
        ComparisonFlag.CAPABILITY_MISMATCH,
        ComparisonFlag.NEGATION_MISMATCH,
    }


# --- unknown handling --------------------------------------------------------


def test_only_deterministic_side_unknown() -> None:
    comparison = compare(
        "The provider guarantees full legal indemnification.",  # no pilot tokens
        llm_result(),
    )
    assert comparison.agreement is NormalizationAgreement.DETERMINISTIC_UNKNOWN


def test_only_llm_side_unknown() -> None:
    comparison = compare(
        "24/7 monitoring for Microsoft Sentinel is required.",
        llm_result(technology="unknown", capability="unknown"),
    )
    assert comparison.agreement is NormalizationAgreement.LLM_UNKNOWN


def test_both_sides_unknown_agree_and_are_flagged() -> None:
    comparison = compare(
        "The provider guarantees full legal indemnification.",
        llm_result(technology="unknown", capability="unknown"),
    )
    assert comparison.agreement is NormalizationAgreement.AGREE
    assert ComparisonFlag.BOTH_UNKNOWN in comparison.flags


def test_missing_llm_result_is_not_evaluated() -> None:
    comparison = compare(
        "24/7 monitoring for Microsoft Sentinel is required.",
        llm_result(validated=False),
    )
    assert comparison.agreement is NormalizationAgreement.NOT_EVALUATED
    assert ComparisonFlag.LLM_RESULT_MISSING in comparison.flags
    assert comparison.llm_technology is None
    assert comparison.llm_capability is None


# --- neutrality --------------------------------------------------------------


def test_comparison_defaults_to_pending_human_evaluation() -> None:
    comparison = compare("24/7 Sentinel monitoring is required.", llm_result())
    assert comparison.human_evaluation_status is HumanEvaluationStatus.PENDING


def test_comparison_never_declares_a_winner() -> None:
    names = set(RequirementNormalizationComparison.model_fields)
    assert not {name for name in names if "winner" in name or "better" in name}
    assert not {name for name in names if "preferred" in name or "correct" in name}
