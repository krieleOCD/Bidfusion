"""Offline tests for the deterministic FakeLlmClient test double."""

from __future__ import annotations

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.fake import FakeLlmClient
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    GuardrailStatus,
    LlmClient,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
    SyntheticGatewayResult,
)
from bidfusion.schemas.common import DataClassification

_MARKER = "top-secret-document-excerpt-should-never-appear-in-calls"


def request(
    *,
    request_id: str = "REQ-FAKE-001",
    guardrail_policy_key: GuardrailPolicyKey = GuardrailPolicyKey.DEFAULT,
    content: str = "Return a synthetic acceptance object.",
) -> StructuredLlmRequest:
    return StructuredLlmRequest(
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        messages=(LlmMessage(role=LlmMessageRole.USER, content=content),),
        response_schema_name="synthetic_gateway_result",
        request_id=request_id,
        data_classification=DataClassification.PUBLIC,
        model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
        guardrail_policy_key=guardrail_policy_key,
    )


def test_fake_is_a_valid_llm_client() -> None:
    fake = FakeLlmClient(
        validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5)
    )

    assert isinstance(fake, LlmClient)


def test_fake_requires_exactly_one_of_output_or_error() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FakeLlmClient()
    with pytest.raises(ValueError, match="exactly one"):
        FakeLlmClient(
            validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5),
            error=LlmGatewayError(LlmGatewayErrorCode.TIMEOUT),
        )


def test_fake_returns_the_configured_structured_output() -> None:
    output = SyntheticGatewayResult(title="accepted", items=("a",), confidence=0.7)
    fake = FakeLlmClient(validated_output=output)

    result = fake.complete_structured(
        request=request(request_id="REQ-FAKE-002"), response_type=SyntheticGatewayResult
    )

    assert result.request_id == "REQ-FAKE-002"
    assert result.validated_output == output


@pytest.mark.parametrize("code", list(LlmGatewayErrorCode))
def test_fake_can_simulate_every_stable_error_code(code: LlmGatewayErrorCode) -> None:
    fake = FakeLlmClient(error=LlmGatewayError(code, request_id="REQ-FAKE-003"))

    with pytest.raises(LlmGatewayError) as raised:
        fake.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is code


def test_fake_rejects_a_response_type_mismatch_as_schema_validation_failed() -> None:
    class OtherResult(SyntheticGatewayResult):
        pass

    fake = FakeLlmClient(
        validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5)
    )

    with pytest.raises(LlmGatewayError) as raised:
        fake.complete_structured(request=request(), response_type=OtherResult)

    assert raised.value.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED


def test_fake_records_call_metadata_without_message_content() -> None:
    fake = FakeLlmClient(
        validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5)
    )

    fake.complete_structured(
        request=request(request_id="REQ-FAKE-004", content=_MARKER),
        response_type=SyntheticGatewayResult,
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.request_id == "REQ-FAKE-004"
    assert call.operation == StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE
    assert _MARKER not in repr(call)
    assert _MARKER not in str(call)
    assert _MARKER not in repr(fake.calls)


def test_fake_tracks_multiple_calls_in_order() -> None:
    fake = FakeLlmClient(
        validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5)
    )

    fake.complete_structured(
        request=request(request_id="REQ-A"), response_type=SyntheticGatewayResult
    )
    fake.complete_structured(
        request=request(request_id="REQ-B"), response_type=SyntheticGatewayResult
    )

    assert [call.request_id for call in fake.calls] == ["REQ-A", "REQ-B"]


def test_fake_marks_guardrail_status_from_the_requested_policy_key() -> None:
    fake = FakeLlmClient(
        validated_output=SyntheticGatewayResult(title="ok", items=(), confidence=0.5)
    )

    default_result = fake.complete_structured(
        request=request(guardrail_policy_key=GuardrailPolicyKey.DEFAULT),
        response_type=SyntheticGatewayResult,
    )
    probe_result = fake.complete_structured(
        request=request(guardrail_policy_key=GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE),
        response_type=SyntheticGatewayResult,
    )

    assert default_result.guardrail_status is GuardrailStatus.NOT_APPLIED
    assert probe_result.guardrail_status is GuardrailStatus.PASSED
