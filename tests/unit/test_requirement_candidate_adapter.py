"""Deterministic RFP-requirement-to-golden-candidate adapter tests.

Every requirement here is synthetic. The adversarial cases pin the
negation rule: negative or excluding language must never be handed to
the matcher as a positive requirement.
"""

from __future__ import annotations

import pytest

from bidfusion.bid_intelligence.matching import adapt_requirement
from bidfusion.bid_intelligence.matching import adapter as adapter_module
from bidfusion.golden_dataset.contracts import CapabilityCategory, Technology
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"


def _requirement(
    text: str,
    *,
    requirement_id: str = "REQ-000001",
    modality: RequirementModality = RequirementModality.MUST,
    normalized: str | None = None,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        bid_id=BID_ID,
        original_text=text,
        normalized_text=normalized,
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


def test_exact_sentinel_requirement_yields_sentinel_hints() -> None:
    adapted = adapt_requirement(
        _requirement("The service MUST support Microsoft Sentinel as the SIEM.")
    )

    assert adapted.technology_hint is Technology.MICROSOFT_SENTINEL
    assert adapted.capability_hints == (CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,)
    assert adapted.candidate.capability_hint is CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT
    assert adapted.candidate.requirement_id == "REQ-000001"
    assert not adapted.negated


def test_defender_xdr_requirement_yields_defender_hints() -> None:
    adapted = adapt_requirement(
        _requirement("The provider MUST support Microsoft Defender XDR for endpoints.")
    )

    assert adapted.technology_hint is Technology.MICROSOFT_DEFENDER_XDR
    assert adapted.capability_hints == (CapabilityCategory.MICROSOFT_DEFENDER_XDR_SUPPORT,)


def test_generic_monitoring_requirement_has_capability_but_no_technology() -> None:
    adapted = adapt_requirement(
        _requirement("24x7 security monitoring is required for all systems.")
    )

    assert adapted.technology_hint is Technology.UNKNOWN
    assert adapted.capability_hints == (CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,)


def test_isolation_transition_and_handover_map_to_pilot_capabilities() -> None:
    cases = {
        "The provider MUST isolate compromised endpoints.": (CapabilityCategory.INCIDENT_ISOLATION),
        "The provider SHOULD describe the transition approach.": (
            CapabilityCategory.TRANSITION_ACTIVATION
        ),
        "A handover to operations MUST be documented.": (CapabilityCategory.HANDOVER_TO_OPERATIONS),
    }
    for text, capability in cases.items():
        adapted = adapt_requirement(_requirement(text))
        assert adapted.capability_hints == (capability,), text


def test_unknown_technology_stays_unknown_without_guessing() -> None:
    adapted = adapt_requirement(
        _requirement("The platform MUST integrate with the QuantumTrace AlphaSIEM appliance.")
    )

    assert adapted.technology_hint is Technology.UNKNOWN
    assert adapted.capability_hints == ()
    assert adapted.candidate.capability_hint is None
    assert not adapted.negated


@pytest.mark.parametrize(
    "text",
    [
        "Splunk support is not required and is excluded from scope.",
        "Endpoint isolation is out of scope for this engagement.",
        "The provider must not isolate endpoints without approval.",
        "The bidder shall not provide Microsoft Sentinel onboarding.",
        "Vectra coverage is no longer required.",
        "A transition workshop will not be required.",
        # H-1 review bypasses — every obvious negative or excluding form
        # below must be flagged so it can never match positively.
        "Splunk support is not required.",
        "Splunk support is not in scope.",
        "Splunk support is not within scope.",
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
        # case, punctuation, line-break, and semicolon variants
        "SPLUNK SUPPORT IS EXCLUDED.",
        "splunk support is not in scope",
        "Splunk support is not in scope!",
        "Splunk support is\nexcluded for this lot.",
        "Splunk support will not\nbe needed.",
        "Sentinel is required; isolation is excluded; handover is expected.",
        # re-review residuals: active-voice exclusion and outside-scope forms
        "The service excludes Splunk support.",
        "The customer excludes Splunk support from this lot.",
        "We exclude Splunk support.",
        "Splunk support is outside the scope.",
        "Splunk support is outside of scope.",
        "Splunk support is outside scope.",
        "Splunk support is out-of-scope.",
    ],
)
def test_negative_or_excluded_language_never_becomes_a_positive_candidate(text: str) -> None:
    adapted = adapt_requirement(_requirement(text, modality=RequirementModality.UNKNOWN))

    assert adapted.negated
    assert adapted.candidate.capability_hint is None


def test_positive_obligations_are_not_flagged_as_negated() -> None:
    for text in (
        "The service MUST support Microsoft Sentinel.",
        "The provider MAY offer an optional on-site workshop.",
        "The supplier SHOULD provide monthly reports.",
        # positive controls from the H-1 fix: obvious positive phrasing
        # must never be over-blocked by the extended rule set.
        "Splunk support is required.",
        "The bidder shall provide Splunk support.",
        "Microsoft Sentinel is required.",
        "Endpoint isolation is required.",
        "Splunk support is required for this lot.",
        "Splunk is in scope.",
    ):
        assert not adapt_requirement(_requirement(text)).negated, text


def test_an_unrelated_negative_sentence_does_not_negate_the_capability() -> None:
    """No blanket contains-not rule: nearby unrelated negation stays inert."""
    adapted = adapt_requirement(
        _requirement("Splunk support is required. The service does not include hardware delivery.")
    )

    assert not adapted.negated
    assert adapted.candidate.capability_hint is CapabilityCategory.SPLUNK_SUPPORT


def test_normalized_text_wins_over_original_text() -> None:
    adapted = adapt_requirement(
        _requirement(
            "REQ-M2: The service MUST support Microsoft Sentinel.",
            normalized="The service MUST support Microsoft Sentinel.",
        )
    )

    assert adapted.candidate.text == "The service MUST support Microsoft Sentinel."


def test_adaptation_is_deterministic_across_repeats() -> None:
    requirement = _requirement("The service MUST support Splunk and 24x7 monitoring.")

    first = adapt_requirement(requirement)
    second = adapt_requirement(requirement)

    assert first == second
    assert first.capability_hints == (
        CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,
        CapabilityCategory.SPLUNK_SUPPORT,
    )


def test_adapter_reuses_the_golden_taxonomies_and_defines_none_of_its_own() -> None:
    """Every hint target is a golden enum member; no competing enum exists."""
    for _, technology in adapter_module._TECHNOLOGY_RULES:
        assert isinstance(technology, Technology)

    import enum
    import inspect

    own_enums = [
        name
        for name, value in inspect.getmembers(adapter_module, inspect.isclass)
        if issubclass(value, enum.Enum) and value.__module__ == adapter_module.__name__
    ]
    assert own_enums == []
