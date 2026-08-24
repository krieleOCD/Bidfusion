"""Contract tests for the RFP API pilot normalization operation.

The wire schema is strict and closed: no free dictionaries, no free
strings where an allowlisted enum exists, every collection bounded, and
the golden taxonomies reused rather than re-invented. An unknown enum
value from the model fails validation — the explicit rule is that the
model must use the ``unknown`` members, never invent taxonomy.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bidfusion.golden_dataset.contracts import CapabilityCategory, ConfidenceBand, Technology
from bidfusion.rfp_api_pilot.contracts import (
    MAX_LIST_ITEMS,
    MAX_REQUIREMENT_TEXT_CHARS,
    PILOT_SCHEMA_VERSION,
    DeterministicNormalizationHints,
    LlmAmbiguityFlag,
    LlmCapability,
    LlmMandatoryStatus,
    LlmNormalizationStatus,
    LlmRequirementNormalization,
    LlmRequirementType,
    RequirementNormalizationRequest,
)


def normalization_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "requirement_id": "REQ-000001",
        "requirement_type": "obligation",
        "mandatory_status": "mandatory",
        "technology": "microsoft_sentinel",
        "capability": "24_7_monitoring",
        "constraints": ["24/7 coverage"],
        "conditions": [],
        "exclusions": [],
        "normalization_status": "normalized",
        "confidence_band": "HIGH",
        "ambiguity_flags": [],
        "rationale": "Explicit Sentinel monitoring obligation with a 24/7 constraint.",
    }
    payload.update(overrides)
    return payload


# --- strict wire schema ------------------------------------------------------


def test_valid_normalization_parses_with_golden_taxonomy_members() -> None:
    normalization = LlmRequirementNormalization.model_validate(normalization_payload())

    assert normalization.schema_version == PILOT_SCHEMA_VERSION
    assert normalization.technology is Technology.MICROSOFT_SENTINEL
    assert normalization.capability is LlmCapability.TWENTY_FOUR_SEVEN_MONITORING
    assert normalization.confidence_band is ConfidenceBand.HIGH


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(
            normalization_payload(compliance_verdict="compliant")
        )


def test_missing_fields_are_rejected() -> None:
    payload = normalization_payload()
    payload.pop("technology")
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(payload)


def test_unknown_enum_values_fail_validation() -> None:
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(
            normalization_payload(technology="azure_sentinel_next")
        )
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(
            normalization_payload(capability="quantum_monitoring")
        )


def test_uncertainty_is_expressed_with_the_unknown_members() -> None:
    normalization = LlmRequirementNormalization.model_validate(
        normalization_payload(
            technology="unknown",
            capability="unknown",
            requirement_type="unknown",
            mandatory_status="unknown",
            normalization_status="unclear",
        )
    )
    assert normalization.technology is Technology.UNKNOWN
    assert normalization.capability is LlmCapability.UNKNOWN


def test_wrong_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(normalization_payload(schema_version="2.0.0"))


def test_null_values_for_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(normalization_payload(capability=None))


def test_collections_and_strings_are_bounded() -> None:
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(
            normalization_payload(constraints=["x"] * (MAX_LIST_ITEMS + 1))
        )
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(normalization_payload(conditions=["y" * 301]))
    with pytest.raises(ValidationError):
        LlmRequirementNormalization.model_validate(normalization_payload(rationale="r" * 501))


def test_wire_schema_has_no_open_dictionaries() -> None:
    schema = LlmRequirementNormalization.model_json_schema()
    assert schema["additionalProperties"] is False


def test_normalization_is_frozen() -> None:
    normalization = LlmRequirementNormalization.model_validate(normalization_payload())
    with pytest.raises(ValidationError):
        normalization.technology = Technology.SPLUNK


# --- taxonomy reuse ----------------------------------------------------------


def test_llm_capability_mirrors_the_golden_taxonomy_plus_unknown() -> None:
    golden_values = {member.value for member in CapabilityCategory}
    llm_values = {member.value for member in LlmCapability}
    assert llm_values == golden_values | {"unknown"}


def test_capability_category_mapping_returns_golden_members_or_none() -> None:
    known = LlmRequirementNormalization.model_validate(normalization_payload())
    assert known.capability_category() is CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING

    unknown = LlmRequirementNormalization.model_validate(
        normalization_payload(capability="unknown")
    )
    assert unknown.capability_category() is None


# --- exclusion semantics -----------------------------------------------------


def test_exclusion_language_is_visible_through_indicates_exclusion() -> None:
    excluded = LlmRequirementNormalization.model_validate(
        normalization_payload(
            requirement_type="exclusion",
            mandatory_status="excluded",
            exclusions=["on-premises log storage is out of scope"],
        )
    )
    assert excluded.indicates_exclusion() is True

    obligation = LlmRequirementNormalization.model_validate(normalization_payload())
    assert obligation.indicates_exclusion() is False


# --- input contract ----------------------------------------------------------


def test_request_carries_one_bounded_requirement_only() -> None:
    request = RequirementNormalizationRequest(
        requirement_id="REQ-000001",
        requirement_text="The service shall support Microsoft Sentinel monitoring 24/7.",
    )
    assert request.schema_version == PILOT_SCHEMA_VERSION
    assert request.modality is None
    assert request.deterministic_hints is None


def test_request_text_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RequirementNormalizationRequest(
            requirement_id="REQ-000001",
            requirement_text="x" * (MAX_REQUIREMENT_TEXT_CHARS + 1),
        )


def test_request_rejects_extra_fields_such_as_document_content() -> None:
    with pytest.raises(ValidationError):
        RequirementNormalizationRequest.model_validate(
            {
                "requirement_id": "REQ-000001",
                "requirement_text": "text",
                "full_document": "entire RFP",
            }
        )


def test_deterministic_hints_are_typed_and_labeled_as_hints() -> None:
    hints = DeterministicNormalizationHints(
        technology=Technology.MICROSOFT_SENTINEL,
        capabilities=(CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,),
        negated=False,
    )
    request = RequirementNormalizationRequest(
        requirement_id="REQ-000001",
        requirement_text="The service shall support Microsoft Sentinel monitoring 24/7.",
        deterministic_hints=hints,
    )
    assert request.deterministic_hints is not None
    assert request.deterministic_hints.technology is Technology.MICROSOFT_SENTINEL


# --- closed vocabularies stay closed -----------------------------------------


def test_pilot_enums_expose_expected_members() -> None:
    assert {member.value for member in LlmRequirementType} == {
        "obligation",
        "optional_request",
        "exclusion",
        "condition",
        "informational",
        "ambiguous",
        "unknown",
    }
    assert {member.value for member in LlmMandatoryStatus} == {
        "mandatory",
        "optional",
        "excluded",
        "conditional",
        "informational",
        "unknown",
    }
    assert {member.value for member in LlmNormalizationStatus} == {
        "normalized",
        "partial",
        "unclear",
    }
    assert "suspected_instruction_text" in {member.value for member in LlmAmbiguityFlag}
