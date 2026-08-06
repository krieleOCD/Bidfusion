"""Offline contract tests for the provider-neutral structured LlmClient port."""

from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    GuardrailStatus,
    LlmCallStatus,
    LlmClient,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    SchemaValidationStatus,
    StructuredLlmOperation,
    StructuredLlmRequest,
    StructuredLlmResult,
    StructuredLlmUsage,
    SyntheticGatewayResult,
)
from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import DataClassification
from bidfusion.schemas.llm import LLMFinishReason

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260806-0001"


def message(content: str = "Return a synthetic acceptance object.") -> LlmMessage:
    return LlmMessage(role=LlmMessageRole.USER, content=content)


def base_request_fields() -> dict[str, object]:
    return {
        "operation": StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        "messages": (message(),),
        "response_schema_name": "synthetic_gateway_result",
        "request_id": "REQ-PORT-001",
        "data_classification": DataClassification.PUBLIC,
        "model_policy_key": ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
    }


def artifact_reference(bid_id: str = BID_ID) -> ArtifactReference:
    content_hash = sha256(b"synthetic content").hexdigest()
    return ArtifactReference(
        artifact_id="ART-20260806-000001",
        bid_id=bid_id,
        run_id=RUN_ID,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref="artifacts/ART-20260806-000001",
        content_hash=content_hash,
    )


def test_allowed_operation_constructs_a_valid_request() -> None:
    request = StructuredLlmRequest.model_validate(base_request_fields())

    assert request.operation is StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE
    assert request.guardrail_policy_key is GuardrailPolicyKey.DEFAULT
    assert request.metadata == {}
    assert request.source_artifact_refs == ()


def test_unknown_operation_is_rejected() -> None:
    fields = base_request_fields()
    fields["operation"] = "arbitrary_free_operation"

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


@pytest.mark.parametrize(
    "extra_field",
    ["model", "provider", "tools", "functions", "images", "guardrail_threshold"],
)
def test_no_free_provider_model_tool_or_guardrail_fields_are_accepted(
    extra_field: str,
) -> None:
    fields = base_request_fields()
    fields[extra_field] = "not-allowed"

    with pytest.raises(ValidationError, match="Extra inputs"):
        StructuredLlmRequest.model_validate(fields)


def test_free_guardrail_policy_key_is_rejected() -> None:
    fields = base_request_fields()
    fields["guardrail_policy_key"] = "my_custom_guardrail"

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_synthetic_prompt_injection_probe_is_an_allowed_guardrail_policy_key() -> None:
    fields = base_request_fields()
    fields["guardrail_policy_key"] = GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE

    request = StructuredLlmRequest.model_validate(fields)

    assert request.guardrail_policy_key is GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE


def test_messages_must_be_non_empty() -> None:
    fields = base_request_fields()
    fields["messages"] = ()

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_message_content_must_be_a_plain_non_empty_string() -> None:
    with pytest.raises(ValidationError):
        LlmMessage(role=LlmMessageRole.USER, content="")


def test_message_rejects_multimodal_or_provider_specific_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        LlmMessage.model_validate({"role": "user", "content": "hi", "image_url": "https://x"})


# --- L1: message and total request content size bounds ------------------------
#
# Bounded for this slice's single synthetic smoke operation, not for future
# full RFP chunks — a content-budget policy for those is explicit future
# work (ADR-0013). ``hide_input_in_errors`` keeps oversized content out of
# the resulting ValidationError message.

_MAX_MESSAGE_CONTENT_CHARS = 16 * 1024
_CONTENT_SENTINEL = "sk-FAKE-OVERSIZED-CONTENT-SENTINEL-"


def test_message_content_at_exactly_the_maximum_is_accepted() -> None:
    content = "x" * _MAX_MESSAGE_CONTENT_CHARS

    built = LlmMessage(role=LlmMessageRole.USER, content=content)

    assert len(built.content) == _MAX_MESSAGE_CONTENT_CHARS


def test_message_content_one_over_the_maximum_is_rejected() -> None:
    content = "x" * (_MAX_MESSAGE_CONTENT_CHARS + 1)

    with pytest.raises(ValidationError):
        LlmMessage(role=LlmMessageRole.USER, content=content)


def test_oversized_message_content_never_appears_in_the_validation_error() -> None:
    content = _CONTENT_SENTINEL + "x" * _MAX_MESSAGE_CONTENT_CHARS

    with pytest.raises(ValidationError) as raised:
        LlmMessage(role=LlmMessageRole.USER, content=content)

    assert _CONTENT_SENTINEL not in str(raised.value)
    assert _CONTENT_SENTINEL not in repr(raised.value)


def test_message_count_is_bounded() -> None:
    fields = base_request_fields()
    fields["messages"] = tuple(message(f"msg {i}") for i in range(21))

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_message_count_at_exactly_the_maximum_is_accepted() -> None:
    fields = base_request_fields()
    fields["messages"] = tuple(message(f"msg {i}") for i in range(20))

    request = StructuredLlmRequest.model_validate(fields)

    assert len(request.messages) == 20


def test_aggregate_message_content_across_multiple_messages_is_bounded() -> None:
    fields = base_request_fields()
    # Each individually well under the per-message cap, but their sum
    # exceeds the aggregate request-content budget.
    fields["messages"] = (
        message("a" * 12_000),
        message("b" * 12_000),
        message("c" * 12_000),
    )

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_oversized_aggregate_content_never_appears_in_the_validation_error() -> None:
    fields = base_request_fields()
    fields["messages"] = (
        message(_CONTENT_SENTINEL + "a" * 12_000),
        message("b" * 12_000),
        message("c" * 12_000),
    )

    with pytest.raises(ValidationError) as raised:
        StructuredLlmRequest.model_validate(fields)

    assert _CONTENT_SENTINEL not in str(raised.value)
    assert _CONTENT_SENTINEL not in repr(raised.value)


def test_metadata_cannot_carry_document_like_full_text() -> None:
    fields = base_request_fields()
    fields["metadata"] = {"note": "x" * 500}

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_metadata_entry_count_is_bounded() -> None:
    fields = base_request_fields()
    fields["metadata"] = {f"key-{i}": "v" for i in range(50)}

    with pytest.raises(ValidationError):
        StructuredLlmRequest.model_validate(fields)


def test_small_metadata_is_accepted() -> None:
    fields = base_request_fields()
    fields["metadata"] = {"source": "smoke-test"}

    request = StructuredLlmRequest.model_validate(fields)

    assert dict(request.metadata) == {"source": "smoke-test"}


def test_source_artifact_refs_require_a_matching_bid_scope() -> None:
    fields = base_request_fields()
    fields["source_artifact_refs"] = (artifact_reference(),)

    with pytest.raises(ValidationError, match="bid_id"):
        StructuredLlmRequest.model_validate(fields)


def test_source_artifact_refs_must_belong_to_the_declared_bid() -> None:
    fields = base_request_fields()
    fields["bid_id"] = BID_ID
    fields["source_artifact_refs"] = (artifact_reference(bid_id="BID-2026-999999"),)

    with pytest.raises(ValidationError, match="bid_id"):
        StructuredLlmRequest.model_validate(fields)


def test_source_artifact_refs_matching_the_bid_are_accepted() -> None:
    fields = base_request_fields()
    fields["bid_id"] = BID_ID
    fields["source_artifact_refs"] = (artifact_reference(),)

    request = StructuredLlmRequest.model_validate(fields)

    assert request.source_artifact_refs[0].bid_id == BID_ID


def test_synthetic_gateway_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        SyntheticGatewayResult.model_validate(
            {"title": "ok", "items": (), "confidence": 0.9, "unexpected": 1}
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_synthetic_gateway_result_bounds_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        SyntheticGatewayResult(title="ok", items=(), confidence=confidence)


def test_synthetic_gateway_result_bounds_item_count() -> None:
    items = tuple(f"item-{i}" for i in range(21))
    with pytest.raises(ValidationError):
        SyntheticGatewayResult(title="ok", items=items, confidence=0.5)


def test_synthetic_gateway_result_rejects_empty_or_oversized_items() -> None:
    with pytest.raises(ValidationError):
        SyntheticGatewayResult(title="ok", items=("",), confidence=0.5)
    with pytest.raises(ValidationError):
        SyntheticGatewayResult(title="ok", items=("x" * 500,), confidence=0.5)


def test_synthetic_gateway_result_accepts_a_valid_payload() -> None:
    result = SyntheticGatewayResult(title="accepted", items=("a", "b"), confidence=0.42)

    assert result.title == "accepted"
    assert result.items == ("a", "b")


def test_structured_llm_usage_total_must_equal_input_plus_output() -> None:
    with pytest.raises(ValidationError, match="total_tokens"):
        StructuredLlmUsage(input_tokens=3, output_tokens=2, total_tokens=999)


def test_structured_llm_usage_accepts_a_consistent_total() -> None:
    usage = StructuredLlmUsage(input_tokens=3, output_tokens=2, total_tokens=5)

    assert usage.total_tokens == 5


def test_structured_llm_result_holds_a_validated_typed_output() -> None:
    output = SyntheticGatewayResult(title="accepted", items=(), confidence=0.9)

    result = StructuredLlmResult[SyntheticGatewayResult](
        request_id="REQ-PORT-002",
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        model_requested="openai/gpt-5.4-mini",
        model_reported="openai/gpt-5.4-mini",
        status=LlmCallStatus.COMPLETED,
        validated_output=output,
        finish_reason=LLMFinishReason.COMPLETED,
        usage=StructuredLlmUsage(input_tokens=5, output_tokens=2, total_tokens=7),
        duration_ms=120,
        attempts=1,
        guardrail_status=GuardrailStatus.NOT_APPLIED,
        schema_validation_status=SchemaValidationStatus.VALID,
    )

    assert result.validated_output == output
    assert result.model_dump().keys().isdisjoint({"raw_response", "api_key", "prompt"})


def test_structured_llm_result_forbids_extra_fields() -> None:
    output = SyntheticGatewayResult(title="accepted", items=(), confidence=0.9)

    with pytest.raises(ValidationError, match="Extra inputs"):
        StructuredLlmResult[SyntheticGatewayResult].model_validate(
            {
                "request_id": "REQ-PORT-003",
                "operation": StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
                "model_requested": "openai/gpt-5.4-mini",
                "status": LlmCallStatus.COMPLETED,
                "validated_output": output,
                "finish_reason": LLMFinishReason.COMPLETED,
                "duration_ms": 1,
                "attempts": 1,
                "guardrail_status": GuardrailStatus.NOT_APPLIED,
                "schema_validation_status": SchemaValidationStatus.VALID,
                "raw_response": {"unexpected": True},
            }
        )


def test_llm_client_is_a_runtime_checkable_provider_neutral_protocol() -> None:
    class Implementation:
        def complete_structured(self, *, request, response_type):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    assert isinstance(Implementation(), LlmClient)
    assert hasattr(LlmClient, "complete_structured")
