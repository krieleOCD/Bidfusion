"""Deterministic, rule-based capability claim extraction.

No AI ontology, no LLM, no semantics: a claim exists only when a fixed
rule finds its token in extracted section text, and every claim points
at the exact sections that triggered it. **No evidence, no claim** — a
rule that matches nothing produces nothing, and there is no fallback.

Every extracted claim is born ``EXTRACTED_UNVERIFIED`` with
``HumanReviewStatus.REQUIRED``. This module cannot produce a
human-confirmed claim; only :func:`~bidfusion.golden_dataset.contracts.
confirm_claim` can, on explicit human input.

The rule table is the pilot's entire capability taxonomy. Confidence is
mechanical: HIGH when evidence spans at least two distinct sources,
MEDIUM otherwise — it grades evidence breadth, never truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ConfidenceBand,
    DocumentType,
    EvidenceReference,
    KnowledgeDocument,
    ServiceFamily,
    Technology,
)

#: Hard cap for this pilot slice.
MAX_CLAIMS = 10

#: Most evidence references kept per claim; further matches add nothing.
_MAX_EVIDENCE_PER_CLAIM = 3

#: Fixed, reviewable negative-context vocabulary. A candidate token
#: occurrence whose local window contains any of these phrases is not
#: evidence: the text is negating, excluding, scoping out, marking as
#: example-only, or delegating to a third party rather than describing a
#: native capability. Deliberately phrase-bound — a bare "not" elsewhere
#: in a sentence does not disqualify an occurrence. Conservative false
#: negatives are acceptable for this pilot; false positive capability
#: claims are not.
_NEGATIVE_CONTEXT = re.compile(
    r"\bnot\s+(?:be\s+)?(?:supported|available|covered|included|offered|provided)\b"
    r"|\b(?:does|do|did|will|would|can|cannot|shall)\s+not\s+(?:support|cover|include|"
    r"provide|offer)\b"
    r"|\bunsupported\b"
    r"|\bnot\s+part\s+of\b"
    r"|\bout(?:side)?\s+(?:of\s+)?(?:the\s+)?scope\b"
    r"|\bexclude[sd]?\b|\bexclusions?\b"
    r"|\bonly\s+as\s+an?\s+example\b|\bexample\s+only\b|\bfor\s+example\b"
    r"|\billustrative\b|\bmentioned\s+only\b"
    r"|\brequires?\s+a\s+third[\s-]part(?:y|ies)\b|\bthird[\s-]party\s+required\b"
    r"|\bthird[\s-]part(?:y|ies)\b[^.!?\n]{0,40}?\brequired\b"
    r"|\bpartner\s+required\b|\bvia\s+a\s+third[\s-]party\b",
    re.IGNORECASE,
)

#: Characters inspected on each side of a candidate token occurrence.
#: Roughly one clause — wide enough for "does not support X" and
#: "X requires a third party", narrow enough that an unrelated negation
#: sentences away cannot veto a clean occurrence.
_CONTEXT_WINDOW_CHARS = 80


def _has_clean_occurrence(body: str, pattern: re.Pattern[str]) -> bool:
    """Whether the section *body* carries at least one unnegated token hit.

    Only body text counts: a technology name in a heading alone is a
    topic marker, not evidence of capability (M-1 review finding). Every
    occurrence is judged by its own bounded window, so one negated
    mention does not disqualify a separate, clean one — and vice versa a
    single clean occurrence is enough.
    """
    for match in pattern.finditer(body):
        window_start = max(0, match.start() - _CONTEXT_WINDOW_CHARS)
        window = body[window_start : match.end() + _CONTEXT_WINDOW_CHARS]
        if _NEGATIVE_CONTEXT.search(window) is None:
            return True
    return False


#: Document families precise enough to source capability statements from.
_EVIDENCE_DOCUMENT_TYPES = frozenset(
    {
        DocumentType.SERVICE_DESCRIPTION,
        DocumentType.QA_TECHNOLOGY_GUIDANCE,
        DocumentType.SERVICE_ACTIVATION_PROCEDURE,
        DocumentType.SERVICE_INSTRUCTION,
        DocumentType.SERVICE_CATALOGUE,
        DocumentType.OVERVIEW,
        DocumentType.STATEMENT_OF_WORK,
    }
)


@dataclass(frozen=True, slots=True)
class _Rule:
    """One deterministic extraction rule."""

    capability: CapabilityCategory
    technology: Technology
    pattern: re.Pattern[str]
    statement: str
    document_technology: Technology | None = None
    service_family: ServiceFamily | None = None


def _tech_rule(
    capability: CapabilityCategory, technology: Technology, token: str, label: str
) -> _Rule:
    return _Rule(
        capability=capability,
        technology=technology,
        pattern=re.compile(token, re.IGNORECASE),
        statement=(
            f"Internal service documentation describes support for {label}. "
            "Extracted by rule; unverified until human review."
        ),
        document_technology=technology,
    )


#: Fixed rule order defines claim order and the cap cutoff.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        capability=CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,
        technology=Technology.GENERIC_MTD,
        pattern=re.compile(r"24\s*[/x×]\s*7|around the clock", re.IGNORECASE),
        statement=(
            "Internal service documentation describes around-the-clock (24/7) "
            "monitoring. Extracted by rule; unverified until human review."
        ),
    ),
    _tech_rule(
        CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,
        Technology.MICROSOFT_SENTINEL,
        r"sentinel",
        "Microsoft Sentinel",
    ),
    _tech_rule(
        CapabilityCategory.MICROSOFT_DEFENDER_XDR_SUPPORT,
        Technology.MICROSOFT_DEFENDER_XDR,
        r"defender",
        "Microsoft Defender XDR",
    ),
    _tech_rule(
        CapabilityCategory.PALO_ALTO_CORTEX_SUPPORT,
        Technology.PALO_ALTO_CORTEX_XDR,
        r"cortex|xsiam",
        "Palo Alto Cortex XDR/XSIAM",
    ),
    _tech_rule(CapabilityCategory.SPLUNK_SUPPORT, Technology.SPLUNK, r"splunk", "Splunk"),
    _tech_rule(CapabilityCategory.VECTRA_SUPPORT, Technology.VECTRA, r"vectra", "Vectra"),
    _Rule(
        capability=CapabilityCategory.INCIDENT_ISOLATION,
        technology=Technology.MANAGED_THREAT_RESPONSE,
        pattern=re.compile(r"isolat", re.IGNORECASE),
        statement=(
            "Internal service documentation describes managed incident/endpoint "
            "isolation. Extracted by rule; unverified until human review."
        ),
        service_family=ServiceFamily.MANAGED_THREAT_RESPONSE,
    ),
    _Rule(
        capability=CapabilityCategory.TRANSITION_ACTIVATION,
        technology=Technology.GENERIC_MTD,
        pattern=re.compile(r"activation|transition", re.IGNORECASE),
        statement=(
            "Internal service documentation describes a documented service "
            "activation/transition procedure. Extracted by rule; unverified "
            "until human review."
        ),
    ),
    _Rule(
        capability=CapabilityCategory.HANDOVER_TO_OPERATIONS,
        technology=Technology.GENERIC_MTD,
        pattern=re.compile(r"handover", re.IGNORECASE),
        statement=(
            "Internal service documentation describes handover to (global) "
            "operations. Extracted by rule; unverified until human review."
        ),
    ),
    _Rule(
        capability=CapabilityCategory.SERVICE_INTEGRATION,
        technology=Technology.ITSM_EBONDING,
        pattern=re.compile(r"ebonding|itsm", re.IGNORECASE),
        statement=(
            "Internal service documentation describes ITSM/eBonding service "
            "integration. Extracted by rule; unverified until human review."
        ),
    ),
)


def extract_claims(documents: tuple[KnowledgeDocument, ...]) -> tuple[CapabilityClaim, ...]:
    """Extract at most :data:`MAX_CLAIMS` evidenced claims, rule by rule."""
    claims: list[CapabilityClaim] = []
    for rule in _RULES:
        if len(claims) >= MAX_CLAIMS:
            break
        evidence = _evidence_for(rule, documents)
        if not evidence:
            continue
        claims.append(
            CapabilityClaim(
                claim_id=_claim_id(rule, evidence),
                service_family=rule.service_family or ServiceFamily.MANAGED_THREAT_DETECTION,
                technology=rule.technology,
                capability=rule.capability,
                statement=rule.statement,
                evidence_refs=evidence,
                confidence_band=_confidence(evidence),
            )
        )
    return tuple(claims[:MAX_CLAIMS])


def _evidence_for(
    rule: _Rule, documents: tuple[KnowledgeDocument, ...]
) -> tuple[EvidenceReference, ...]:
    evidence: list[EvidenceReference] = []
    for document in documents:
        if document.document_type not in _EVIDENCE_DOCUMENT_TYPES:
            continue
        if rule.document_technology is not None and (
            document.technology is not rule.document_technology
        ):
            continue
        if rule.service_family is not None and (document.service_family is not rule.service_family):
            continue
        for section in document.sections:
            if not _has_clean_occurrence(section.text, rule.pattern):
                continue
            evidence.append(
                EvidenceReference(
                    source_id=section.source_id,
                    section_id=section.section_id,
                    locator=section.source_locator,
                    source_version=document.source_version,
                )
            )
            if len(evidence) >= _MAX_EVIDENCE_PER_CLAIM:
                return tuple(evidence)
    return tuple(evidence)


def _confidence(evidence: tuple[EvidenceReference, ...]) -> ConfidenceBand:
    sources = {reference.source_id for reference in evidence}
    return ConfidenceBand.HIGH if len(sources) >= 2 else ConfidenceBand.MEDIUM


def _claim_id(rule: _Rule, evidence: tuple[EvidenceReference, ...]) -> str:
    material = "\n".join(
        (
            rule.capability.value,
            rule.technology.value,
            *(f"{ref.source_id}:{ref.section_id}" for ref in evidence),
        )
    )
    return f"GCL-{sha256(material.encode()).hexdigest()[:12]}"
