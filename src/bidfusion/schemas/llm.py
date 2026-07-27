"""Provider-independent contracts sent to the enterprise LLM Gateway."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel, DataClassification
from bidfusion.schemas.ids import BidId


class ReasoningRequirement(StrEnum):
    """Requested reasoning depth, not a model selection."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContextWindowRequirement(StrEnum):
    """Coarse requested context capacity."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class CostPriority(StrEnum):
    """Relative cost priority used by gateway routing policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelCapabilities(BidfusionModel):
    """Capabilities required by a business module."""

    vision: bool = False
    structured_output: bool = False
    reasoning: ReasoningRequirement = ReasoningRequirement.MEDIUM
    context_window: ContextWindowRequirement = ContextWindowRequirement.MEDIUM


class ModelDataPolicy(BidfusionModel):
    """Data handling needs declared to the gateway."""

    classification: DataClassification = DataClassification.CONFIDENTIAL
    local_processing_preferred: bool = True


class ModelRequirements(BidfusionModel):
    """What a call requires; model and provider routing stay in the gateway."""

    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    data_policy: ModelDataPolicy = Field(default_factory=ModelDataPolicy)
    cost_priority: CostPriority = CostPriority.MEDIUM


class StructuredOutputSpec(BidfusionModel):
    """Named, provider-independent JSON Schema expected from an LLM call."""

    name: str = Field(min_length=1)
    json_schema: dict[str, JsonValue]


class ExecutionScope(BidfusionModel):
    """Contract-level bid boundary for one external-capability call."""

    bid_id: BidId


class LLMRequest(BidfusionModel):
    """Owned request contract with capability requirements, never model selection."""

    request_id: str = Field(min_length=1)
    scope: ExecutionScope | None = None
    requirements: ModelRequirements = Field(default_factory=ModelRequirements)
    prompt: str | None = Field(default=None, min_length=1)
    input_artifacts: tuple[ArtifactReference, ...] = Field(default_factory=tuple)
    output_spec: StructuredOutputSpec | None = None

    @model_validator(mode="after")
    def _request_matches_declared_capabilities(self) -> LLMRequest:
        if self.prompt is None and not self.input_artifacts:
            msg = "an LLM request requires a prompt or at least one input artifact"
            raise ValueError(msg)
        if self.input_artifacts and self.scope is None:
            msg = "LLM requests with bid-bound input artifacts require an execution scope"
            raise ValueError(msg)
        if self.scope is not None and any(
            artifact.bid_id != self.scope.bid_id for artifact in self.input_artifacts
        ):
            msg = "LLM input artifacts must belong to the execution scope bid"
            raise ValueError(msg)
        capabilities = self.requirements.capabilities
        if self.output_spec is not None and not capabilities.structured_output:
            msg = "an output specification requires structured_output capability"
            raise ValueError(msg)
        return self


class LLMFinishReason(StrEnum):
    """Provider-normalized successful termination reason."""

    COMPLETED = "completed"
    LENGTH = "length"


class LLMUsage(BidfusionModel):
    """Optional normalized usage counters returned by a gateway."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class LLMResponse(BidfusionModel):
    """Owned response contract without provider SDK objects."""

    request_id: str = Field(min_length=1)
    output_text: str | None = Field(default=None, min_length=1)
    structured_output: dict[str, JsonValue] | None = None
    finish_reason: LLMFinishReason
    route_id: str = Field(
        min_length=1,
        description="Opaque gateway route identifier for audit, not provider selection.",
    )
    usage: LLMUsage | None = None

    @model_validator(mode="after")
    def _has_output(self) -> LLMResponse:
        if self.output_text is None and self.structured_output is None:
            msg = "an LLM response requires text or structured output"
            raise ValueError(msg)
        return self
