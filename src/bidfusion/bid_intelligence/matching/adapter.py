"""Deterministic adapter from extracted RFP requirements to golden candidates.

No model call, no scoring, no guessing: fixed word-bounded token rules
map requirement text onto the *existing* golden taxonomies. Technology
hints are values of the golden :class:`Technology` enum; capability
hints come from the golden matcher's own token scan
(:func:`bidfusion.golden_dataset.matching.recognized_capabilities`), so
this module introduces no taxonomy of its own.

Negative and excluding requirement language ("not required", "excluded",
"not in scope", "must not") is detected with bounded rules. A requirement
recognized as negated is never handed to the matcher as a positive
requirement; a mixed positive-and-negative statement is conservatively
treated as negated as a whole and surfaces as UNKNOWN for review.
Under-classification is preferred over false precision, and anything
unclear stays ``unknown``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    RequirementCandidate,
    Technology,
)
from bidfusion.golden_dataset.matching import recognized_capabilities
from bidfusion.schemas.extraction import Requirement

ADAPTER_NAME = "bidfusion-requirement-candidate-adapter"
ADAPTER_VERSION = "0.1.0"

#: Ordered (pattern, technology) rules for prose, most specific first.
#: Every target is a member of the golden Technology taxonomy; the table
#: adds no platform of its own. Prose needs word-bounded patterns, which
#: is why the golden filename token table is mirrored rather than reused
#: verbatim — the targets stay identical.
_TECHNOLOGY_RULES: tuple[tuple[re.Pattern[str], Technology], ...] = (
    (re.compile(r"\bsentinel\b", re.IGNORECASE), Technology.MICROSOFT_SENTINEL),
    (re.compile(r"\bdefender\b", re.IGNORECASE), Technology.MICROSOFT_DEFENDER_XDR),
    (re.compile(r"\bxsiam\b", re.IGNORECASE), Technology.PALO_ALTO_XSIAM),
    (re.compile(r"\bcortex\b", re.IGNORECASE), Technology.PALO_ALTO_CORTEX_XDR),
    (re.compile(r"\bsplunk\b", re.IGNORECASE), Technology.SPLUNK),
    (re.compile(r"\bvectra\b", re.IGNORECASE), Technology.VECTRA),
    (
        re.compile(r"\bmanaged threat response\b", re.IGNORECASE),
        Technology.MANAGED_THREAT_RESPONSE,
    ),
    (
        re.compile(r"\bmanaged threat detection\b", re.IGNORECASE),
        Technology.GENERIC_MTD,
    ),
)

#: Bounded negation and exclusion phrases. Only language that clearly
#: negates or excludes counts; "optional" and "may" remain positive
#: (weak) obligations, not negations. Every pattern is word-bounded, so
#: "exclude/excludes/excluded" fires only as a whole word ("excluding"
#: does not) and a nearby "not" alone never negates anything — there is
#: deliberately no blanket contains-"not" rule.
#:
#: One phrase match negates the *whole* requirement (single-pass pilot,
#: no clause parser): a mixed statement such as "Sentinel is required
#: but isolation is excluded" conservatively becomes UNKNOWN rather
#: than risking a positive candidate for the excluded clause. False
#: negatives are acceptable; false positive matches are not.
_NEGATION_RULES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnot\s+required\b", re.IGNORECASE),
    re.compile(r"\bno\s+longer\s+required\b", re.IGNORECASE),
    re.compile(r"\bnot\s+needed\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\b", re.IGNORECASE),
    re.compile(r"\bshall\s+not\b", re.IGNORECASE),
    re.compile(r"\bexclude[sd]?\b", re.IGNORECASE),
    re.compile(r"\bout[\s-]+of[\s-]+scope\b", re.IGNORECASE),
    re.compile(r"\boutside\s+(?:of\s+)?(?:the\s+)?scope\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:in|within)\s+scope\b", re.IGNORECASE),
    re.compile(
        r"\bwill\s+not\s+be\s+(?:required|provided|part|needed|included)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bdo(?:es)?\s+not\s+require\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:a\s+)?requirement\b", re.IGNORECASE),
    re.compile(r"\bnot\s+part\s+of\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:\w+\s+){1,4}(?:is|are)\s+required\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class AdaptedRequirement:
    """One RFP requirement normalized for the golden pilot matcher.

    ``candidate`` is only meaningful for matching when ``negated`` is
    ``False``; the assessment service never matches a negated
    requirement positively.
    """

    candidate: RequirementCandidate
    technology_hint: Technology
    capability_hints: tuple[CapabilityCategory, ...]
    negated: bool


def requirement_text(requirement: Requirement) -> str:
    """The text the pilot normalizes: normalized when present, else original."""
    return requirement.normalized_text or requirement.original_text


def adapt_requirement(requirement: Requirement) -> AdaptedRequirement:
    """Deterministically normalize one extracted requirement.

    Uses only fields the RFP extraction actually provides. The capability
    hint handed to the candidate is the first capability the golden
    matcher's own token scan recognizes — never a competing
    classification — and stays unset when nothing is recognized.
    """
    text = requirement_text(requirement)
    negated = detect_negation(text)
    capabilities = recognized_capabilities(text)
    candidate = RequirementCandidate(
        requirement_id=requirement.requirement_id,
        text=text,
        technology_hint=None,
        capability_hint=capabilities[0] if capabilities and not negated else None,
    )
    return AdaptedRequirement(
        candidate=candidate,
        technology_hint=detect_technology(text),
        capability_hints=capabilities,
        negated=negated,
    )


def detect_technology(text: str) -> Technology:
    """First matching golden technology for prose text, else ``UNKNOWN``."""
    for pattern, technology in _TECHNOLOGY_RULES:
        if pattern.search(text):
            return technology
    return Technology.UNKNOWN


def detect_negation(text: str) -> bool:
    """Whether the requirement language negates or excludes the obligation."""
    return any(pattern.search(text) for pattern in _NEGATION_RULES)
