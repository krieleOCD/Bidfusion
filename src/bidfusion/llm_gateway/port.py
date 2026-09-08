"""Provider-neutral structured LLM port (ADR-0013).

This module must stay completely provider-neutral: nothing here may know
about Orange, LiteLLM, ``/chat/completions``, bearer tokens, OpenAI-style
``choices``, concrete guardrail names, or any HTTP transport. Those details
belong exclusively in ``policy.py``, ``settings.py``, and
``orange_proxy.py``. Business/domain code depends only on the contracts and
the ``LlmClient`` protocol defined here.

``LlmClient`` is the foundation for later schema-validated, policy-governed
model operations. The existing general ``LLMPort``
(:mod:`bidfusion.ports`) remains unchanged for backward compatibility with
its existing consumers; this port is additive, not a replacement. Any
future consolidation or deprecation is a separate decision (ADR-0013).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel, Confidence, DataClassification, FrozenMapping
from bidfusion.schemas.ids import BidId, RunId
from bidfusion.schemas.llm import LLMFinishReason

_MAX_METADATA_ENTRIES = 20
_MAX_METADATA_KEY_LENGTH = 64
_MAX_METADATA_VALUE_LENGTH = 200

#: Bounded for this slice's single synthetic smoke operation, not for
#: future full RFP chunks — a content-budget policy for those operations
#: requires its own explicit, separately reviewed decision rather than
#: silently raising these limits (ADR-0013).
_MAX_MESSAGE_CONTENT_CHARS = 16 * 1024
_MAX_MESSAGES = 20
_MAX_TOTAL_MESSAGE_CONTENT_CHARS = 32 * 1024


class StructuredLlmOperation(StrEnum):
    """Allowlisted business operations. No free operation names.

    Future operations (e.g. requirement extraction, complex review) are
    documented in ``policy.py`` but deliberately not added as members
    here until they are actually implemented — an undeclared operation
    cannot be constructed or executed.

    ``RFP_REQUIREMENT_NORMALIZATION`` normalizes exactly one anonymized,
    security-cleared requirement text into a strict structured candidate
    interpretation. The output is a machine normalization candidate for
    human evaluation, never a compliance or deliverability decision.
    """

    SYNTHETIC_STRUCTURED_SMOKE = "synthetic_structured_smoke"
    RFP_REQUIREMENT_NORMALIZATION = "rfp_requirement_normalization"


class ModelPolicyKey(StrEnum):
    """Allowlisted keys into the model policy. Never a free model name."""

    SYNTHETIC_STRUCTURED_SMOKE = "synthetic_structured_smoke"
    RFP_REQUIREMENT_NORMALIZATION = "rfp_requirement_normalization"


class GuardrailPolicyKey(StrEnum):
    """Allowlisted keys into the guardrail policy. Never a free guardrail name."""

    DEFAULT = "default"
    SYNTHETIC_PROMPT_INJECTION_PROBE = "synthetic_prompt_injection_probe"


class LlmMessageRole(StrEnum):
    """Typed message roles. No provider-specific roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmMessage(BidfusionModel):
    """One typed, text-only conversation turn. No tools, no multimodal content.

    ``content`` is bounded to a size appropriate for this slice's single
    synthetic smoke operation (see ``_MAX_MESSAGE_CONTENT_CHARS`` above),
    not for future full RFP chunks. ``hide_input_in_errors`` keeps an
    oversized value out of the resulting ValidationError message.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    role: LlmMessageRole
    content: str = Field(min_length=1, max_length=_MAX_MESSAGE_CONTENT_CHARS)


class StructuredLlmRequest(BidfusionModel):
    """Owned, narrow request contract for one schema-validated model call."""

    model_config = ConfigDict(hide_input_in_errors=True)

    operation: StructuredLlmOperation
    messages: tuple[LlmMessage, ...] = Field(min_length=1, max_length=_MAX_MESSAGES)
    response_schema_name: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1)
    bid_id: BidId | None = None
    run_id: RunId | None = None
    source_artifact_refs: tuple[ArtifactReference, ...] = Field(default_factory=tuple)
    data_classification: DataClassification
    model_policy_key: ModelPolicyKey
    guardrail_policy_key: GuardrailPolicyKey = GuardrailPolicyKey.DEFAULT
    max_output_tokens: int | None = Field(default=None, ge=1, le=4096)
    metadata: FrozenMapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _total_message_content_is_bounded(self) -> StructuredLlmRequest:
        total = sum(len(message.content) for message in self.messages)
        if total > _MAX_TOTAL_MESSAGE_CONTENT_CHARS:
            msg = f"total message content exceeds {_MAX_TOTAL_MESSAGE_CONTENT_CHARS} characters"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _metadata_cannot_carry_document_like_text(self) -> StructuredLlmRequest:
        if len(self.metadata) > _MAX_METADATA_ENTRIES:
            msg = f"metadata cannot have more than {_MAX_METADATA_ENTRIES} entries"
            raise ValueError(msg)
        for key, value in self.metadata.items():
            if len(key) > _MAX_METADATA_KEY_LENGTH:
                msg = f"metadata key exceeds {_MAX_METADATA_KEY_LENGTH} characters"
                raise ValueError(msg)
            if len(value) > _MAX_METADATA_VALUE_LENGTH:
                msg = f"metadata value exceeds {_MAX_METADATA_VALUE_LENGTH} characters"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _source_artifact_refs_stay_bid_scoped(self) -> StructuredLlmRequest:
        if not self.source_artifact_refs:
            return self
        if self.bid_id is None:
            msg = "source_artifact_refs require a matching bid_id scope"
            raise ValueError(msg)
        for artifact in self.source_artifact_refs:
            if artifact.bid_id != self.bid_id:
                msg = "source_artifact_refs must belong to the declared bid_id"
                raise ValueError(msg)
        return self


class LlmCallStatus(StrEnum):
    """BidFusion-normalized outcome status of a completed call."""

    COMPLETED = "completed"


class GuardrailStatus(StrEnum):
    """Normalized guardrail outcome. A block is a typed error, not a status."""

    NOT_APPLIED = "not_applied"
    PASSED = "passed"


class SchemaValidationStatus(StrEnum):
    """Normalized schema-validation outcome. A failure is a typed error, not a status."""

    VALID = "valid"


class StructuredLlmUsage(BidfusionModel):
    """Normalized token usage. ``total_tokens`` must equal input + output."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def _total_matches_parts(self) -> StructuredLlmUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            msg = "total_tokens must equal input_tokens + output_tokens"
            raise ValueError(msg)
        return self


class StructuredLlmResult[ResponseT: BaseModel](BidfusionModel):
    """Owned, normalized result of one structured LLM call. No raw provider payload."""

    request_id: str = Field(min_length=1)
    operation: StructuredLlmOperation
    model_requested: str = Field(min_length=1)
    model_reported: str | None = None
    status: LlmCallStatus
    validated_output: ResponseT
    finish_reason: LLMFinishReason
    usage: StructuredLlmUsage | None = None
    duration_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)
    guardrail_status: GuardrailStatus
    schema_validation_status: SchemaValidationStatus


class SyntheticGatewayResult(BidfusionModel):
    """Small synthetic structured contract for the ``synthetic_structured_smoke`` operation."""

    title: str = Field(min_length=1, max_length=200)
    items: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = Field(
        default_factory=tuple, max_length=20
    )
    confidence: Confidence


T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LlmClient(Protocol):
    """Provider-neutral, schema-validated structured completion capability."""

    def complete_structured(
        self,
        *,
        request: StructuredLlmRequest,
        response_type: type[T],
    ) -> StructuredLlmResult[T]:
        """Return a normalized, schema-validated result or raise ``LlmGatewayError``."""
        ...
