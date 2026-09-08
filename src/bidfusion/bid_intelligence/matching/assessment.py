"""The requirement-to-golden-knowledge assessment service.

Orchestrates the narrow bridge path deterministically:

    extracted RFP requirement
      -> deterministic adapter (normalization, negation, hints)
      -> existing golden pilot matcher
      -> match plus resolved evidence
      -> RequirementKnowledgeAssessment (human review required)

The service takes an already-loaded :class:`ClaimsSnapshot` instead of a
store path, so deep bid-domain code never touches the golden runtime
store — snapshot loading stays a separate, injectable step
(:mod:`bidfusion.bid_intelligence.matching.claims_access`). It mutates
nothing: golden claims pass through unchanged, and no result can leave
this module without ``HumanReviewStatus.REQUIRED``.
"""

from __future__ import annotations

from hashlib import sha256

from bidfusion.bid_intelligence.matching.adapter import adapt_requirement, requirement_text
from bidfusion.bid_intelligence.matching.claims_access import ClaimsSnapshot
from bidfusion.bid_intelligence.matching.contracts import (
    ASSESSMENT_VERSION,
    KnowledgeAssessmentResult,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    RequirementLanguage,
)
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ClaimStatus,
    EvidenceReference,
    MatchStatus,
)
from bidfusion.golden_dataset.matching import match_requirement
from bidfusion.schemas.extraction import Requirement

_NEGATED_RATIONALE = (
    "Deterministic pilot: the requirement language is negative or excluding, "
    "so no positive candidate match is raised. Needs review."
)
_NOT_EVALUATED_RATIONALE = (
    "No deterministic verdict was produced because the golden knowledge "
    "snapshot was not available for matching. This is not a capability gap."
)


def assess_requirements(
    requirements: tuple[Requirement, ...],
    snapshot: ClaimsSnapshot,
) -> KnowledgeAssessmentResult:
    """Deterministically assess every requirement against the snapshot.

    Requirements arrive as validated :class:`Requirement` contracts —
    construction already enforced bid isolation and canonical
    provenance, so an object that reaches this service is usable. The
    result preserves input order and both provenance chains.
    """
    evaluate = snapshot.state is KnowledgeStoreState.AVAILABLE
    assessments = tuple(
        _assess_one(requirement, snapshot.claims, evaluate=evaluate) for requirement in requirements
    )
    return KnowledgeAssessmentResult(
        store_state=snapshot.state,
        store_note=snapshot.note,
        claim_count=len(snapshot.claims),
        assessments=assessments,
    )


def _assess_one(
    requirement: Requirement,
    claims: tuple[CapabilityClaim, ...],
    *,
    evaluate: bool,
) -> RequirementKnowledgeAssessment:
    adapted = adapt_requirement(requirement)

    def build(
        *,
        match_status: MatchStatus | None,
        rationale: str,
        matched_claim_id: str | None = None,
        matched_capability: CapabilityCategory | None = None,
        knowledge_claim_status: ClaimStatus | None = None,
        evidence_refs: tuple[EvidenceReference, ...] = (),
    ) -> RequirementKnowledgeAssessment:
        return RequirementKnowledgeAssessment(
            assessment_id=_assessment_id(requirement),
            bid_id=requirement.bid_id,
            requirement_id=requirement.requirement_id,
            requirement_text=requirement_text(requirement),
            requirement_modality=requirement.modality,
            requirement_source=requirement.source,
            additional_requirement_sources=requirement.additional_sources,
            requirement_language=(
                RequirementLanguage.NEGATED_OR_EXCLUDED
                if adapted.negated
                else RequirementLanguage.OBLIGATION
            ),
            technology_hint=adapted.technology_hint,
            capability_hints=adapted.capability_hints,
            match_status=match_status,
            matched_claim_id=matched_claim_id,
            matched_capability=matched_capability,
            knowledge_claim_status=knowledge_claim_status,
            evidence_refs=evidence_refs,
            rationale=rationale,
        )

    if not evaluate:
        return build(match_status=None, rationale=_NOT_EVALUATED_RATIONALE)
    if adapted.negated:
        return build(match_status=MatchStatus.UNKNOWN, rationale=_NEGATED_RATIONALE)

    match = match_requirement(adapted.candidate, claims)
    claim = next((item for item in claims if item.claim_id == match.claim_id), None)
    return build(
        match_status=match.match_status,
        matched_claim_id=match.claim_id,
        matched_capability=claim.capability if claim is not None else None,
        knowledge_claim_status=claim.status if claim is not None else None,
        evidence_refs=match.evidence_refs,
        rationale=match.rationale,
    )


def _assessment_id(requirement: Requirement) -> str:
    """Deterministic, content-bound assessment identifier."""
    digest = sha256(
        f"{ASSESSMENT_VERSION}|{requirement.bid_id}|{requirement.requirement_id}|"
        f"{requirement_text(requirement)}".encode()
    ).hexdigest()
    return f"RKA-{digest[:12]}"
