"""Bid-side LLM normalizer service for the anonymized real-RFP pilot.

``normalize_requirement_with_llm`` sends exactly one bounded,
security-cleared requirement through an injected provider-neutral
``LlmClient`` (in production the Orange Proxy adapter — never a direct
provider SDK) and wraps the outcome:

- validated :class:`LlmRequirementNormalization`, or
- a stable failure status from a closed taxonomy.

The wrapper never carries the raw prompt, the raw model response, or
any chain-of-thought (none is requested). Provenance to the original
:class:`Requirement` travels as ``bid_id`` + ``requirement_id`` + a
SHA-256 digest of the exact normalized text.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import Field, model_validator

from bidfusion.bid_intelligence.matching.adapter import requirement_text
from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.port import (
    LlmClient,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
)
from bidfusion.rfp_api_pilot.contracts import (
    MAX_REQUIREMENT_TEXT_CHARS,
    LlmRequirementNormalization,
    RequirementNormalizationRequest,
)
from bidfusion.rfp_api_pilot.presend_check import PresendWarning, check_requirement_text
from bidfusion.rfp_api_pilot.prompt import PROMPT_VERSION, build_messages
from bidfusion.schemas.common import BidfusionModel, DataClassification, Sha256Digest
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.ids import BidId, RequirementId

LLM_NORMALIZER_NAME = "bidfusion-llm-requirement-normalizer"
LLM_NORMALIZER_VERSION = "0.1.0"

_RESPONSE_SCHEMA_NAME = "llm_requirement_normalization"
_MAX_OUTPUT_TOKENS = 1024


class LlmNormalizationValidationStatus(StrEnum):
    """Closed outcome taxonomy for one normalization attempt."""

    VALIDATED = "VALIDATED"
    GATEWAY_FAILED = "GATEWAY_FAILED"
    REQUIREMENT_ID_MISMATCH = "REQUIREMENT_ID_MISMATCH"
    BLOCKED_BY_PRESEND_CHECK = "BLOCKED_BY_PRESEND_CHECK"
    TEXT_BOUND_EXCEEDED = "TEXT_BOUND_EXCEEDED"


class LlmNormalizedRequirement(BidfusionModel):
    """One requirement's machine-normalization candidate, or its stable failure.

    ``VALIDATED`` means only "the model returned schema-valid output for
    the right requirement" — never correct, approved, or compliant.
    """

    producer: str = LLM_NORMALIZER_NAME
    producer_version: str = LLM_NORMALIZER_VERSION
    bid_id: BidId
    requirement_id: RequirementId
    operation: StructuredLlmOperation
    prompt_version: str = Field(min_length=1, max_length=20)
    validation_status: LlmNormalizationValidationStatus
    normalization: LlmRequirementNormalization | None = None
    gateway_error_code: LlmGatewayErrorCode | None = None
    presend_warnings: tuple[PresendWarning, ...] = Field(default_factory=tuple, max_length=10)
    model_requested: str | None = Field(default=None, min_length=1)
    model_reported: str | None = Field(default=None, min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    attempts: int | None = Field(default=None, ge=1)
    normalized_at: datetime
    requirement_text_sha256: Sha256Digest

    @model_validator(mode="after")
    def _states_are_coherent(self) -> LlmNormalizedRequirement:
        if self.normalized_at.tzinfo is None:
            msg = "normalized_at must be timezone-aware"
            raise ValueError(msg)
        validated = self.validation_status is LlmNormalizationValidationStatus.VALIDATED
        if validated and self.normalization is None:
            msg = "a validated result must carry its normalization"
            raise ValueError(msg)
        if not validated and self.normalization is not None:
            msg = "a failed attempt must not carry a normalization payload"
            raise ValueError(msg)
        if validated and self.gateway_error_code is not None:
            msg = "a validated result cannot carry a gateway error code"
            raise ValueError(msg)
        gateway_failed = self.validation_status is LlmNormalizationValidationStatus.GATEWAY_FAILED
        if gateway_failed and self.gateway_error_code is None:
            msg = "a gateway failure must name its stable error code"
            raise ValueError(msg)
        blocked = self.validation_status is (
            LlmNormalizationValidationStatus.BLOCKED_BY_PRESEND_CHECK
        )
        if blocked and not self.presend_warnings:
            msg = "a presend block must carry at least one warning"
            raise ValueError(msg)
        return self


def normalize_requirement_with_llm(
    requirement: Requirement,
    *,
    client: LlmClient,
    now: datetime,
    presend_override: bool = False,
) -> LlmNormalizedRequirement:
    """Normalize one extracted requirement through the injected LLM client.

    ``presend_override`` is the explicit operator override of the
    labeled pilot policy: without it, any pre-send identifier warning
    blocks the external call. Warnings stay recorded either way.
    """
    text = requirement_text(requirement)
    digest = sha256(text.encode("utf-8")).hexdigest()

    def wrapper(
        status: LlmNormalizationValidationStatus,
        *,
        normalization: LlmRequirementNormalization | None = None,
        gateway_error_code: LlmGatewayErrorCode | None = None,
        warnings: tuple[PresendWarning, ...] = (),
        model_requested: str | None = None,
        model_reported: str | None = None,
        duration_ms: int | None = None,
        attempts: int | None = None,
    ) -> LlmNormalizedRequirement:
        return LlmNormalizedRequirement(
            bid_id=requirement.bid_id,
            requirement_id=requirement.requirement_id,
            operation=StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION,
            prompt_version=PROMPT_VERSION,
            validation_status=status,
            normalization=normalization,
            gateway_error_code=gateway_error_code,
            presend_warnings=warnings,
            model_requested=model_requested,
            model_reported=model_reported,
            duration_ms=duration_ms,
            attempts=attempts,
            normalized_at=now,
            requirement_text_sha256=digest,
        )

    if len(text) > MAX_REQUIREMENT_TEXT_CHARS:
        return wrapper(LlmNormalizationValidationStatus.TEXT_BOUND_EXCEEDED)

    warnings = check_requirement_text(text)
    if warnings and not presend_override:
        return wrapper(LlmNormalizationValidationStatus.BLOCKED_BY_PRESEND_CHECK, warnings=warnings)

    normalization_request = RequirementNormalizationRequest(
        requirement_id=requirement.requirement_id,
        requirement_text=text,
        modality=requirement.modality,
    )
    request = StructuredLlmRequest(
        operation=StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION,
        messages=build_messages(normalization_request),
        response_schema_name=_RESPONSE_SCHEMA_NAME,
        request_id=f"RFPNORM-{requirement.bid_id}-{requirement.requirement_id}",
        bid_id=requirement.bid_id,
        data_classification=DataClassification.ANONYMIZED_INTERNAL_PILOT,
        model_policy_key=ModelPolicyKey.RFP_REQUIREMENT_NORMALIZATION,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )

    try:
        result = client.complete_structured(
            request=request, response_type=LlmRequirementNormalization
        )
    except LlmGatewayError as failure:
        return wrapper(
            LlmNormalizationValidationStatus.GATEWAY_FAILED,
            gateway_error_code=failure.code,
            warnings=warnings,
        )

    if result.validated_output.requirement_id != requirement.requirement_id:
        return wrapper(
            LlmNormalizationValidationStatus.REQUIREMENT_ID_MISMATCH,
            warnings=warnings,
            model_requested=result.model_requested,
            model_reported=result.model_reported,
            duration_ms=result.duration_ms,
            attempts=result.attempts,
        )

    return wrapper(
        LlmNormalizationValidationStatus.VALIDATED,
        normalization=result.validated_output,
        warnings=warnings,
        model_requested=result.model_requested,
        model_reported=result.model_reported,
        duration_ms=result.duration_ms,
        attempts=result.attempts,
    )
