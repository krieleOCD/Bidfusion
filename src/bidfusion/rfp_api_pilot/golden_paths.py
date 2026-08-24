"""Golden evidence matching for both normalization paths.

Path A (authoritative, unchanged): the deterministic
``RequirementCandidate`` from :func:`adapt_requirement` through the
existing golden matcher. Path B: a second candidate derived from the
validated LLM normalization, through the SAME local deterministic
matcher. The model never searches, ranks, or receives golden evidence;
golden claims pass through read-only.

Semantics mirror the existing assessment service: a negated
(deterministic) or excluding (LLM) reading is never matched positively —
it surfaces as ``UNKNOWN`` without a matcher call.
"""

from __future__ import annotations

from pydantic import Field

from bidfusion.bid_intelligence.matching.adapter import AdaptedRequirement
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ClaimId,
    MatchStatus,
    RequirementCandidate,
    Technology,
)
from bidfusion.golden_dataset.matching import match_requirement
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizationValidationStatus,
    LlmNormalizedRequirement,
)
from bidfusion.schemas.common import BidfusionModel


class MatchPathResult(BidfusionModel):
    """One path's golden-matcher outcome for a requirement."""

    technology: Technology | None = None
    capability_hint: CapabilityCategory | None = None
    match_status: MatchStatus
    matched_claim_id: ClaimId | None = None
    evidence_count: int = Field(ge=0)


class GoldenMatchComparison(BidfusionModel):
    """Side-by-side golden verdicts; ``llm`` is absent when no valid result exists."""

    requirement_id: str = Field(min_length=1)
    deterministic: MatchPathResult
    llm: MatchPathResult | None = None
    match_agreement: bool | None = None


_UNMATCHED_EXCLUSION = MatchStatus.UNKNOWN


def _match_path(
    candidate: RequirementCandidate,
    claims: tuple[CapabilityClaim, ...],
    *,
    technology: Technology | None,
    excluded: bool,
) -> MatchPathResult:
    if excluded:
        return MatchPathResult(
            technology=technology,
            capability_hint=candidate.capability_hint,
            match_status=_UNMATCHED_EXCLUSION,
            matched_claim_id=None,
            evidence_count=0,
        )
    match = match_requirement(candidate, claims)
    return MatchPathResult(
        technology=technology,
        capability_hint=candidate.capability_hint,
        match_status=match.match_status,
        matched_claim_id=match.claim_id,
        evidence_count=len(match.evidence_refs),
    )


def compare_golden_matches(
    adapted: AdaptedRequirement,
    llm: LlmNormalizedRequirement,
    claims: tuple[CapabilityClaim, ...],
) -> GoldenMatchComparison:
    """Run both candidate paths through the existing matcher and compare."""
    deterministic = _match_path(
        adapted.candidate,
        claims,
        technology=adapted.technology_hint,
        excluded=adapted.negated,
    )

    normalization = llm.normalization
    if (
        llm.validation_status is not LlmNormalizationValidationStatus.VALIDATED
        or normalization is None
    ):
        return GoldenMatchComparison(
            requirement_id=adapted.candidate.requirement_id,
            deterministic=deterministic,
            llm=None,
            match_agreement=None,
        )

    excluded = normalization.indicates_exclusion()
    llm_candidate = RequirementCandidate(
        requirement_id=adapted.candidate.requirement_id,
        text=adapted.candidate.text,
        technology_hint=(
            None if normalization.technology is Technology.UNKNOWN else normalization.technology
        ),
        capability_hint=None if excluded else normalization.capability_category(),
    )
    llm_path = _match_path(
        llm_candidate,
        claims,
        technology=normalization.technology,
        excluded=excluded,
    )
    return GoldenMatchComparison(
        requirement_id=adapted.candidate.requirement_id,
        deterministic=deterministic,
        llm=llm_path,
        match_agreement=deterministic.match_status is llm_path.match_status,
    )
