"""Deterministic, offline ``LlmClient`` test double (ADR-0013).

The primary test and later offline-eval adapter: no network module import,
no production HTTP logic, and no message content retained beyond what a
caller explicitly reads off the returned result.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    GuardrailStatus,
    LlmCallStatus,
    SchemaValidationStatus,
    StructuredLlmRequest,
    StructuredLlmResult,
    StructuredLlmUsage,
)
from bidfusion.schemas.llm import LLMFinishReason


@dataclass(frozen=True, slots=True)
class RecordedFakeCall:
    """Call metadata captured by :class:`FakeLlmClient`. Never message content."""

    request_id: str
    operation: str
    model_policy_key: str
    guardrail_policy_key: str


class FakeLlmClient:
    """Configurable, network-free stand-in for the ``LlmClient`` port."""

    def __init__(
        self,
        *,
        validated_output: BaseModel | None = None,
        error: LlmGatewayError | None = None,
        model_requested: str = "openai/gpt-5.4-mini",
    ) -> None:
        if (validated_output is None) == (error is None):
            msg = "FakeLlmClient requires exactly one of validated_output or error"
            raise ValueError(msg)
        self._validated_output = validated_output
        self._error = error
        self._model_requested = model_requested
        self._calls: list[RecordedFakeCall] = []

    @property
    def calls(self) -> tuple[RecordedFakeCall, ...]:
        """Metadata for every call made so far, in order."""
        return tuple(self._calls)

    def complete_structured[T: BaseModel](
        self,
        *,
        request: StructuredLlmRequest,
        response_type: type[T],
    ) -> StructuredLlmResult[T]:
        """Return the configured structured output or raise the configured error."""
        self._calls.append(
            RecordedFakeCall(
                request_id=request.request_id,
                operation=request.operation.value,
                model_policy_key=request.model_policy_key.value,
                guardrail_policy_key=request.guardrail_policy_key.value,
            )
        )
        if self._error is not None:
            raise self._error

        output = self._validated_output
        if not isinstance(output, response_type):
            raise LlmGatewayError(
                LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED,
                request_id=request.request_id,
            )

        guardrail_status = (
            GuardrailStatus.NOT_APPLIED
            if request.guardrail_policy_key is GuardrailPolicyKey.DEFAULT
            else GuardrailStatus.PASSED
        )
        # The isinstance check above narrows ``output`` to ``T``, so mypy
        # infers ``StructuredLlmResult[T]`` here without an explicit
        # subscript (``response_type`` is a runtime value and cannot be
        # used as one).
        return StructuredLlmResult(
            request_id=request.request_id,
            operation=request.operation,
            model_requested=self._model_requested,
            model_reported=self._model_requested,
            status=LlmCallStatus.COMPLETED,
            validated_output=output,
            finish_reason=LLMFinishReason.COMPLETED,
            usage=StructuredLlmUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            duration_ms=0,
            attempts=1,
            guardrail_status=guardrail_status,
            schema_validation_status=SchemaValidationStatus.VALID,
        )
