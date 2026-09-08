"""Deterministic-vs-LLM normalization comparison. No automatic winner.

Fixed, documented agreement rules:

1. An LLM attempt without a validated normalization is ``NOT_EVALUATED``.
2. If exactly one side is wholly unknown, the verdict names that side
   (``DETERMINISTIC_UNKNOWN`` / ``LLM_UNKNOWN``). "Wholly unknown" means
   no technology, no capability, and no negation/exclusion signal.
3. If both sides are wholly unknown they agree (flagged ``BOTH_UNKNOWN``).
4. Otherwise three dimensions are compared — technology, capability,
   negation/exclusion — yielding ``AGREE`` (all), ``DISAGREE`` (none),
   or ``PARTIAL_AGREEMENT`` with a mismatch flag per dimension.

The comparison never declares one method correct; that judgement is the
human evaluator's (:mod:`bidfusion.rfp_api_pilot.evaluation`).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from bidfusion.bid_intelligence.matching.adapter import AdaptedRequirement
from bidfusion.golden_dataset.contracts import CapabilityCategory, Technology
from bidfusion.rfp_api_pilot.contracts import (
    MAX_ITEM_CHARS,
    MAX_LIST_ITEMS,
    LlmCapability,
)
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizationValidationStatus,
    LlmNormalizedRequirement,
)
from bidfusion.schemas.common import BidfusionModel


class NormalizationAgreement(StrEnum):
    """How the deterministic and LLM normalizations relate."""

    AGREE = "AGREE"
    PARTIAL_AGREEMENT = "PARTIAL_AGREEMENT"
    DISAGREE = "DISAGREE"
    DETERMINISTIC_UNKNOWN = "DETERMINISTIC_UNKNOWN"
    LLM_UNKNOWN = "LLM_UNKNOWN"
    NOT_EVALUATED = "NOT_EVALUATED"


class ComparisonFlag(StrEnum):
    """Closed vocabulary making each disagreement dimension visible."""

    TECHNOLOGY_MISMATCH = "TECHNOLOGY_MISMATCH"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    NEGATION_MISMATCH = "NEGATION_MISMATCH"
    BOTH_UNKNOWN = "BOTH_UNKNOWN"
    LLM_RESULT_MISSING = "LLM_RESULT_MISSING"


class HumanEvaluationStatus(StrEnum):
    """Whether a human has evaluated this comparison yet."""

    PENDING = "PENDING"
    RECORDED = "RECORDED"


class RequirementNormalizationComparison(BidfusionModel):
    """Side-by-side record of both normalizations for one requirement."""

    requirement_id: str = Field(min_length=1)
    deterministic_technology: Technology
    deterministic_capabilities: tuple[CapabilityCategory, ...] = Field(
        default_factory=tuple, max_length=len(CapabilityCategory)
    )
    deterministic_negated: bool
    llm_technology: Technology | None = None
    llm_capability: LlmCapability | None = None
    llm_excluded: bool | None = None
    llm_exclusions: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_LIST_ITEMS)
    agreement: NormalizationAgreement
    flags: tuple[ComparisonFlag, ...] = Field(default_factory=tuple, max_length=len(ComparisonFlag))
    human_evaluation_status: HumanEvaluationStatus = HumanEvaluationStatus.PENDING


def compare_normalizations(
    adapted: AdaptedRequirement,
    llm: LlmNormalizedRequirement,
) -> RequirementNormalizationComparison:
    """Apply the fixed agreement rules to one requirement's two normalizations."""
    requirement_id = adapted.candidate.requirement_id

    def build(
        agreement: NormalizationAgreement,
        flags: tuple[ComparisonFlag, ...] = (),
    ) -> RequirementNormalizationComparison:
        normalization = llm.normalization
        return RequirementNormalizationComparison(
            requirement_id=requirement_id,
            deterministic_technology=adapted.technology_hint,
            deterministic_capabilities=adapted.capability_hints,
            deterministic_negated=adapted.negated,
            llm_technology=None if normalization is None else normalization.technology,
            llm_capability=None if normalization is None else normalization.capability,
            llm_excluded=None if normalization is None else normalization.indicates_exclusion(),
            llm_exclusions=(
                ()
                if normalization is None
                else tuple(item[:MAX_ITEM_CHARS] for item in normalization.exclusions)
            ),
            agreement=agreement,
            flags=flags,
        )

    if (
        llm.validation_status is not LlmNormalizationValidationStatus.VALIDATED
        or llm.normalization is None
    ):
        return build(NormalizationAgreement.NOT_EVALUATED, (ComparisonFlag.LLM_RESULT_MISSING,))

    normalization = llm.normalization
    llm_excluded = normalization.indicates_exclusion()

    deterministic_unknown = (
        adapted.technology_hint is Technology.UNKNOWN
        and not adapted.capability_hints
        and not adapted.negated
    )
    llm_unknown = (
        normalization.technology is Technology.UNKNOWN
        and normalization.capability is LlmCapability.UNKNOWN
        and not llm_excluded
    )

    if deterministic_unknown and llm_unknown:
        return build(NormalizationAgreement.AGREE, (ComparisonFlag.BOTH_UNKNOWN,))
    if deterministic_unknown:
        return build(NormalizationAgreement.DETERMINISTIC_UNKNOWN)
    if llm_unknown:
        return build(NormalizationAgreement.LLM_UNKNOWN)

    technology_agrees = adapted.technology_hint is normalization.technology
    llm_capability = normalization.capability_category()
    if llm_capability is None:
        capability_agrees = not adapted.capability_hints
    else:
        capability_agrees = llm_capability in adapted.capability_hints
    negation_agrees = adapted.negated == llm_excluded

    flags: list[ComparisonFlag] = []
    if not technology_agrees:
        flags.append(ComparisonFlag.TECHNOLOGY_MISMATCH)
    if not capability_agrees:
        flags.append(ComparisonFlag.CAPABILITY_MISMATCH)
    if not negation_agrees:
        flags.append(ComparisonFlag.NEGATION_MISMATCH)

    if not flags:
        return build(NormalizationAgreement.AGREE)
    if len(flags) == 3:
        return build(NormalizationAgreement.DISAGREE, tuple(flags))
    return build(NormalizationAgreement.PARTIAL_AGREEMENT, tuple(flags))
