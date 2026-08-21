"""Deterministic requirement-to-capability pilot matching.

Keyword and taxonomy lookups only: no embeddings, no vector database, no
graph, no LLM, no RAG. A requirement text is scanned for fixed capability
tokens; each recognized aspect either finds a usable claim or it does
not, and the verdict follows mechanically:

- no aspect recognized → ``UNKNOWN`` (the pilot cannot judge the text);
- every aspect covered by a usable claim → ``MATCHED``;
- some covered → ``PARTIAL``;
- none covered, but an aspect is only covered by rejected/superseded
  claims → ``EVIDENCE_REQUIRED`` (the capability was once claimed and
  needs fresh evidence);
- none covered at all → ``GAP``.

A usable claim is ``EXTRACTED_UNVERIFIED`` or ``HUMAN_CONFIRMED`` —
matching *presents* unverified claims but never upgrades them, so every
result stays ``HumanReviewStatus.REQUIRED``.

The five ``SYNTHETIC_DEMO_REQUIREMENTS`` are the slice's only matching
inputs: they are invented demo texts, never real customer RFP content.
"""

from __future__ import annotations

import re

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ClaimStatus,
    EvidenceReference,
    HumanReviewStatus,
    MatchCandidate,
    MatchStatus,
    RequirementCandidate,
)

#: Ordered (pattern, capability) taxonomy; every match adds one aspect.
_ASPECT_TOKENS: tuple[tuple[re.Pattern[str], CapabilityCategory], ...] = (
    (
        re.compile(r"24\s*[/x×]\s*7|around the clock", re.IGNORECASE),
        CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,
    ),
    (re.compile(r"sentinel", re.IGNORECASE), CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT),
    (re.compile(r"defender", re.IGNORECASE), CapabilityCategory.MICROSOFT_DEFENDER_XDR_SUPPORT),
    (re.compile(r"cortex|xsiam", re.IGNORECASE), CapabilityCategory.PALO_ALTO_CORTEX_SUPPORT),
    (re.compile(r"splunk", re.IGNORECASE), CapabilityCategory.SPLUNK_SUPPORT),
    (re.compile(r"vectra", re.IGNORECASE), CapabilityCategory.VECTRA_SUPPORT),
    (re.compile(r"isolat", re.IGNORECASE), CapabilityCategory.INCIDENT_ISOLATION),
    (
        re.compile(r"transition|activation", re.IGNORECASE),
        CapabilityCategory.TRANSITION_ACTIVATION,
    ),
    (re.compile(r"handover", re.IGNORECASE), CapabilityCategory.HANDOVER_TO_OPERATIONS),
    (
        re.compile(r"ebonding|itsm|service integration", re.IGNORECASE),
        CapabilityCategory.SERVICE_INTEGRATION,
    ),
)

_USABLE_CLAIM_STATES = frozenset({ClaimStatus.EXTRACTED_UNVERIFIED, ClaimStatus.HUMAN_CONFIRMED})

#: The slice's five synthetic demo requirements. SYNTHETIC DEMO INPUT —
#: written for this pilot, not taken from any customer RFP.
SYNTHETIC_DEMO_REQUIREMENTS: tuple[RequirementCandidate, ...] = (
    RequirementCandidate(
        requirement_id="DEMO-REQ-001",
        text="24/7 security monitoring is required.",
    ),
    RequirementCandidate(
        requirement_id="DEMO-REQ-002",
        text="The service must support Microsoft Sentinel.",
    ),
    RequirementCandidate(
        requirement_id="DEMO-REQ-003",
        text="The bidder must support Microsoft Defender XDR.",
    ),
    RequirementCandidate(
        requirement_id="DEMO-REQ-004",
        text="The service must support automated or managed endpoint isolation.",
    ),
    RequirementCandidate(
        requirement_id="DEMO-REQ-005",
        text="A documented transition and handover process is required.",
    ),
)


def match_requirement(
    requirement: RequirementCandidate,
    claims: tuple[CapabilityClaim, ...],
) -> MatchCandidate:
    """Deterministic verdict for one requirement against the claim set."""
    aspects = _recognized_aspects(requirement)
    if not aspects:
        return MatchCandidate(
            requirement_id=requirement.requirement_id,
            claim_id=None,
            match_status=MatchStatus.UNKNOWN,
            rationale=(
                "No pilot capability token was recognized in the requirement text; "
                "the deterministic pilot cannot judge it."
            ),
            evidence_refs=(),
            human_review_status=HumanReviewStatus.REQUIRED,
        )

    covered: list[tuple[CapabilityCategory, CapabilityClaim]] = []
    stale: list[CapabilityCategory] = []
    missing: list[CapabilityCategory] = []
    for aspect in aspects:
        usable = [
            claim
            for claim in claims
            if claim.capability is aspect and claim.status in _USABLE_CLAIM_STATES
        ]
        if usable:
            covered.append((aspect, usable[0]))
        elif any(claim.capability is aspect for claim in claims):
            stale.append(aspect)
        else:
            missing.append(aspect)

    if covered and not stale and not missing:
        status = MatchStatus.MATCHED
    elif covered:
        status = MatchStatus.PARTIAL
    elif stale:
        status = MatchStatus.EVIDENCE_REQUIRED
    else:
        status = MatchStatus.GAP

    evidence: tuple[EvidenceReference, ...] = tuple(
        reference for _, claim in covered for reference in claim.evidence_refs
    )
    return MatchCandidate(
        requirement_id=requirement.requirement_id,
        claim_id=covered[0][1].claim_id if covered else None,
        match_status=status,
        rationale=_rationale(covered, stale, missing),
        evidence_refs=evidence,
        human_review_status=HumanReviewStatus.REQUIRED,
    )


def match_requirements(
    requirements: tuple[RequirementCandidate, ...],
    claims: tuple[CapabilityClaim, ...],
) -> tuple[MatchCandidate, ...]:
    """Match every requirement independently, in input order."""
    return tuple(match_requirement(requirement, claims) for requirement in requirements)


def _recognized_aspects(requirement: RequirementCandidate) -> tuple[CapabilityCategory, ...]:
    aspects: list[CapabilityCategory] = []
    for pattern, capability in _ASPECT_TOKENS:
        if pattern.search(requirement.text) and capability not in aspects:
            aspects.append(capability)
    if requirement.capability_hint is not None and requirement.capability_hint not in aspects:
        aspects.append(requirement.capability_hint)
    return tuple(aspects)


def _rationale(
    covered: list[tuple[CapabilityCategory, CapabilityClaim]],
    stale: list[CapabilityCategory],
    missing: list[CapabilityCategory],
) -> str:
    parts: list[str] = []
    if covered:
        names = ", ".join(aspect.value for aspect, _ in covered)
        parts.append(f"claims cover: {names}")
    if stale:
        names = ", ".join(aspect.value for aspect in stale)
        parts.append(f"only rejected or superseded claims exist for: {names}")
    if missing:
        names = ", ".join(aspect.value for aspect in missing)
        parts.append(f"no claim exists for: {names}")
    return "Deterministic pilot match — " + "; ".join(parts) + "."
