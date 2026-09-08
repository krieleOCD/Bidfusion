"""Normalizer service tests: wrapper semantics, gating, and no raw persistence.

``normalize_requirement_with_llm`` takes the authoritative extracted
:class:`Requirement`, sends exactly one bounded prompt through an
injected ``LlmClient``, and returns a wrapper that carries either the
validated normalization or a stable failure status — never a raw prompt,
never a raw model response, never chain-of-thought.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import BaseModel, ValidationError

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.fake import FakeLlmClient
from bidfusion.llm_gateway.port import (
    GuardrailStatus,
    LlmCallStatus,
    SchemaValidationStatus,
    StructuredLlmOperation,
    StructuredLlmRequest,
    StructuredLlmResult,
)
from bidfusion.rfp_api_pilot.contracts import LlmRequirementNormalization
from bidfusion.rfp_api_pilot.presend_check import PresendWarningKind
from bidfusion.rfp_api_pilot.prompt import PROMPT_VERSION, SYSTEM_INSTRUCTIONS
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizationValidationStatus,
    LlmNormalizedRequirement,
    normalize_requirement_with_llm,
)
from bidfusion.schemas.common import DataClassification, RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.llm import LLMFinishReason
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def requirement_for(text: str, *, requirement_id: str = "REQ-000001") -> Requirement:
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


def normalization_for(requirement_id: str = "REQ-000001") -> LlmRequirementNormalization:
    return LlmRequirementNormalization.model_validate(
        {
            "schema_version": "1.0.0",
            "requirement_id": requirement_id,
            "requirement_type": "obligation",
            "mandatory_status": "mandatory",
            "technology": "microsoft_sentinel",
            "capability": "24_7_monitoring",
            "constraints": ["24/7 coverage"],
            "normalization_status": "normalized",
            "confidence_band": "HIGH",
            "rationale": "Explicit Sentinel monitoring obligation.",
        }
    )


@dataclass
class RecordingClient:
    """LlmClient double that records full requests for prompt assertions."""

    output: LlmRequirementNormalization
    requests: list[StructuredLlmRequest] = field(default_factory=list)

    def complete_structured[T: BaseModel](
        self,
        *,
        request: StructuredLlmRequest,
        response_type: type[T],
    ) -> StructuredLlmResult[T]:
        self.requests.append(request)
        assert isinstance(self.output, response_type)
        return StructuredLlmResult(
            request_id=request.request_id,
            operation=request.operation,
            model_requested="openai/gpt-5.4-mini",
            model_reported="openai/gpt-5.4-mini",
            status=LlmCallStatus.COMPLETED,
            validated_output=self.output,
            finish_reason=LLMFinishReason.COMPLETED,
            usage=None,
            duration_ms=42,
            attempts=1,
            guardrail_status=GuardrailStatus.NOT_APPLIED,
            schema_validation_status=SchemaValidationStatus.VALID,
        )


# --- happy path --------------------------------------------------------------


def test_valid_result_yields_a_validated_wrapper_with_provenance() -> None:
    requirement = requirement_for("The service shall support Microsoft Sentinel 24/7.")
    client = FakeLlmClient(validated_output=normalization_for())

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    assert wrapped.validation_status is LlmNormalizationValidationStatus.VALIDATED
    assert wrapped.normalization is not None
    assert wrapped.gateway_error_code is None
    assert wrapped.requirement_id == "REQ-000001"
    assert wrapped.bid_id == BID_ID
    assert wrapped.operation is StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION
    assert wrapped.prompt_version == PROMPT_VERSION
    assert wrapped.normalized_at == NOW
    expected_digest = sha256(b"The service shall support Microsoft Sentinel 24/7.").hexdigest()
    assert wrapped.requirement_text_sha256 == expected_digest


def test_request_is_bounded_scoped_and_classified_for_the_pilot() -> None:
    requirement = requirement_for("The service shall support Microsoft Sentinel 24/7.")
    client = RecordingClient(output=normalization_for())

    normalize_requirement_with_llm(requirement, client=client, now=NOW)

    (request,) = client.requests
    assert request.operation is StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION
    assert request.data_classification is DataClassification.ANONYMIZED_INTERNAL_PILOT
    assert request.bid_id == BID_ID
    assert len(request.messages) == 2
    assert request.messages[0].content == SYSTEM_INSTRUCTIONS
    assert "The service shall support Microsoft Sentinel 24/7." in request.messages[1].content
    # Only the one requirement travels: no filename, no path, no document hash.
    full_prompt = request.messages[0].content + request.messages[1].content
    assert "anonymized-rfp.docx" not in full_prompt
    assert "a" * 64 not in full_prompt


# --- failure taxonomy --------------------------------------------------------


def test_gateway_failure_becomes_a_stable_wrapper_status() -> None:
    requirement = requirement_for("Sentinel monitoring is required.")
    client = FakeLlmClient(error=LlmGatewayError(LlmGatewayErrorCode.TIMEOUT, request_id="REQ-X"))

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    assert wrapped.validation_status is LlmNormalizationValidationStatus.GATEWAY_FAILED
    assert wrapped.gateway_error_code is LlmGatewayErrorCode.TIMEOUT
    assert wrapped.normalization is None


def test_mismatched_requirement_id_discards_the_payload() -> None:
    requirement = requirement_for("Sentinel monitoring is required.")
    client = FakeLlmClient(validated_output=normalization_for("REQ-000099"))

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    assert wrapped.validation_status is LlmNormalizationValidationStatus.REQUIREMENT_ID_MISMATCH
    assert wrapped.normalization is None


def test_presend_warning_blocks_the_external_call_by_default() -> None:
    requirement = requirement_for("Send reports to soc@customer-example.com daily.")
    client = RecordingClient(output=normalization_for())

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    assert client.requests == []
    assert wrapped.validation_status is (LlmNormalizationValidationStatus.BLOCKED_BY_PRESEND_CHECK)
    assert {warning.kind for warning in wrapped.presend_warnings} == {
        PresendWarningKind.EMAIL_ADDRESS
    }
    assert wrapped.normalization is None


def test_explicit_operator_override_sends_despite_presend_warnings() -> None:
    requirement = requirement_for("Send reports to soc@customer-example.com daily.")
    client = RecordingClient(output=normalization_for())

    wrapped = normalize_requirement_with_llm(
        requirement, client=client, now=NOW, presend_override=True
    )

    assert len(client.requests) == 1
    assert wrapped.validation_status is LlmNormalizationValidationStatus.VALIDATED
    assert wrapped.presend_warnings  # the warnings stay visible even when overridden


def test_oversized_requirement_text_is_never_sent() -> None:
    requirement = requirement_for("x" * 4001)
    client = RecordingClient(output=normalization_for())

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    assert client.requests == []
    assert wrapped.validation_status is LlmNormalizationValidationStatus.TEXT_BOUND_EXCEEDED
    assert wrapped.normalization is None


# --- wrapper contract --------------------------------------------------------


def test_wrapper_persists_no_raw_prompt_or_response() -> None:
    requirement = requirement_for("The service shall support Microsoft Sentinel 24/7.")
    client = FakeLlmClient(validated_output=normalization_for())

    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    dumped = wrapped.model_dump_json()
    assert SYSTEM_INSTRUCTIONS[:40] not in dumped
    field_names = set(LlmNormalizedRequirement.model_fields)
    assert not field_names & {"messages", "prompt", "raw_response", "reasoning", "chain_of_thought"}


def test_wrapper_rejects_incoherent_states() -> None:
    requirement = requirement_for("Sentinel monitoring is required.")
    client = FakeLlmClient(validated_output=normalization_for())
    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    with pytest.raises(ValidationError):
        wrapped.model_copy(update={"normalization": None}).model_validate(
            wrapped.model_copy(update={"normalization": None}).model_dump()
        )
    with pytest.raises(ValidationError):
        LlmNormalizedRequirement.model_validate(
            wrapped.model_dump() | {"gateway_error_code": "timeout"}
        )


def test_wrapper_requires_timezone_aware_timestamp() -> None:
    requirement = requirement_for("Sentinel monitoring is required.")
    client = FakeLlmClient(validated_output=normalization_for())
    wrapped = normalize_requirement_with_llm(requirement, client=client, now=NOW)

    with pytest.raises(ValidationError):
        LlmNormalizedRequirement.model_validate(
            wrapped.model_dump() | {"normalized_at": "2026-08-21T12:00:00"}
        )
