"""Strict, versioned contracts for the ``rfp_requirement_normalization`` operation.

The wire schema (:class:`LlmRequirementNormalization`) is what the model
must return: closed enums, bounded strings and collections, no open
dictionaries, ``extra="forbid"`` everywhere. The golden taxonomies are
reused, never re-invented — ``technology`` is the golden
:class:`~bidfusion.golden_dataset.contracts.Technology` enum, and
``capability`` is the golden capability key set plus an explicit
``unknown`` member (:class:`LlmCapability`, kept in lockstep by a guard
test).

Explicit unknown-value rule: a model output using any value outside the
closed vocabularies FAILS validation (surfacing as the gateway's
``SCHEMA_VALIDATION_FAILED``). The model is instructed to use the
``unknown`` members when uncertain; nothing is silently coerced.

The output is a ``MACHINE_NORMALIZATION_CANDIDATE`` — never validated,
correct, approved, or compliant. Human evaluation is required.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from bidfusion.golden_dataset.contracts import CapabilityCategory, ConfidenceBand, Technology
from bidfusion.schemas.common import BidfusionModel, RequirementModality, SemanticVersion

PILOT_SCHEMA_VERSION = "1.0.0"

#: Pilot bound for one requirement text sent to the model. One bounded
#: requirement per call — never a document, section, or package.
MAX_REQUIREMENT_TEXT_CHARS = 4000
MAX_LIST_ITEMS = 10
MAX_ITEM_CHARS = 300
MAX_RATIONALE_CHARS = 500
MAX_REQUIREMENT_ID_CHARS = 64

_BoundedItem = Annotated[str, Field(min_length=1, max_length=MAX_ITEM_CHARS)]


class LlmRequirementType(StrEnum):
    """What kind of statement the requirement text expresses."""

    OBLIGATION = "obligation"
    OPTIONAL_REQUEST = "optional_request"
    EXCLUSION = "exclusion"
    CONDITION = "condition"
    INFORMATIONAL = "informational"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class LlmMandatoryStatus(StrEnum):
    """Strength of the obligation as the model reads the text."""

    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"
    CONDITIONAL = "conditional"
    INFORMATIONAL = "informational"
    UNKNOWN = "unknown"


class LlmNormalizationStatus(StrEnum):
    """How completely the model could normalize the supplied text."""

    NORMALIZED = "normalized"
    PARTIAL = "partial"
    UNCLEAR = "unclear"


class LlmAmbiguityFlag(StrEnum):
    """Closed ambiguity vocabulary; free-text ambiguity notes are not allowed."""

    UNCLEAR_OBLIGATION = "unclear_obligation"
    MULTIPLE_REQUIREMENTS = "multiple_requirements"
    CONFLICTING_STATEMENTS = "conflicting_statements"
    MISSING_CONTEXT = "missing_context"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    NON_REQUIREMENT_TEXT = "non_requirement_text"
    SUSPECTED_INSTRUCTION_TEXT = "suspected_instruction_text"


class LlmCapability(StrEnum):
    """The golden capability keys plus an explicit ``unknown``.

    Not a competing taxonomy: every non-``unknown`` member mirrors a
    :class:`~bidfusion.golden_dataset.contracts.CapabilityCategory`
    value one-to-one (enforced by a guard test), and ``unknown`` exists
    only because the model needs a closed way to say "no golden
    capability applies or I am not sure".
    """

    TWENTY_FOUR_SEVEN_MONITORING = "24_7_monitoring"
    MICROSOFT_SENTINEL_SUPPORT = "microsoft_sentinel_support"
    MICROSOFT_DEFENDER_XDR_SUPPORT = "microsoft_defender_xdr_support"
    PALO_ALTO_CORTEX_SUPPORT = "palo_alto_cortex_support"
    SPLUNK_SUPPORT = "splunk_support"
    VECTRA_SUPPORT = "vectra_support"
    INCIDENT_ISOLATION = "incident_isolation"
    TRANSITION_ACTIVATION = "transition_activation"
    HANDOVER_TO_OPERATIONS = "handover_to_operations"
    SERVICE_INTEGRATION = "service_integration"
    UNKNOWN = "unknown"


class LlmRequirementNormalization(BidfusionModel):
    """Strict structured interpretation of ONE requirement. Wire schema v1.0.0.

    This is a ``MACHINE_NORMALIZATION_CANDIDATE``: reviewable model
    output, not truth. It never states whether Orange Cyberdefense can
    deliver, whether the requirement is compliant, or whether any golden
    claim is true.
    """

    schema_version: Literal["1.0.0"]
    requirement_id: str = Field(min_length=1, max_length=MAX_REQUIREMENT_ID_CHARS)
    requirement_type: LlmRequirementType
    mandatory_status: LlmMandatoryStatus
    technology: Technology
    capability: LlmCapability
    constraints: tuple[_BoundedItem, ...] = Field(default_factory=tuple, max_length=MAX_LIST_ITEMS)
    conditions: tuple[_BoundedItem, ...] = Field(default_factory=tuple, max_length=MAX_LIST_ITEMS)
    exclusions: tuple[_BoundedItem, ...] = Field(default_factory=tuple, max_length=MAX_LIST_ITEMS)
    normalization_status: LlmNormalizationStatus
    confidence_band: ConfidenceBand
    ambiguity_flags: tuple[LlmAmbiguityFlag, ...] = Field(
        default_factory=tuple, max_length=len(LlmAmbiguityFlag)
    )
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)

    def capability_category(self) -> CapabilityCategory | None:
        """The golden capability this normalization maps to, if any."""
        if self.capability is LlmCapability.UNKNOWN:
            return None
        return CapabilityCategory(self.capability.value)

    def indicates_exclusion(self) -> bool:
        """Whether the model read the text as negating or excluding."""
        return (
            self.requirement_type is LlmRequirementType.EXCLUSION
            or self.mandatory_status is LlmMandatoryStatus.EXCLUDED
        )


class DeterministicNormalizationHints(BidfusionModel):
    """Optional deterministic results, clearly labeled as fallible hints.

    Present only for explicit comparison experiments; the default pilot
    flow sends no hints so the challenger stays unbiased.
    """

    technology: Technology
    capabilities: tuple[CapabilityCategory, ...] = Field(
        default_factory=tuple, max_length=len(CapabilityCategory)
    )
    negated: bool


class RequirementNormalizationRequest(BidfusionModel):
    """Bounded input for one normalization call.

    Exactly one anonymized, security-cleared requirement. By
    construction there is no field for a document, a section, golden
    knowledge content, previous answers, pricing, customer identifiers,
    or filesystem paths — such content cannot be carried.
    """

    schema_version: SemanticVersion = PILOT_SCHEMA_VERSION
    requirement_id: str = Field(min_length=1, max_length=MAX_REQUIREMENT_ID_CHARS)
    requirement_text: str = Field(min_length=1, max_length=MAX_REQUIREMENT_TEXT_CHARS)
    modality: RequirementModality | None = None
    deterministic_hints: DeterministicNormalizationHints | None = None
