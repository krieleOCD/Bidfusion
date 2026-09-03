"""Bounded deterministic requirement signals for rule-based extraction v0.2.

Three small, independently testable signal groups:

- structural identifiers (numbered clauses, ``§`` clauses, ``Abschnitt``/
  ``Ziffer``/``Anforderung``/``Kriterium`` prefixes, bounded alphanumeric
  criterion identifiers such as ``A-12``),
- positive modality signals (bounded German procurement vocabulary plus
  the v0.1 English keywords), and
- explicit negation/exclusion signals.

Everything here is deterministic pattern matching over one text block.
No lookups, no learned components, no document-specific phrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from bidfusion.schemas.common import RequirementModality

# ---------------------------------------------------------------------------
# Structural identifiers
# ---------------------------------------------------------------------------

#: Prefixes that belong to other conventions and are never rule-B/C
#: structural identifiers (explicit labels, vulnerability identifiers).
_EXCLUDED_ALPHA_PREFIXES = frozenset({"REQ", "CVE"})

_DOTTED_NUMBER = re.compile(r"^(?P<token>\d{1,2}(?:\.\d{1,3})+\.?|\d{1,2}\.)\s+(?P<rest>\S.*)$")
_SECTION_SIGN = re.compile(r"^(?P<token>§\s?\d{1,3}(?:\.\d{1,2})*)\s+(?P<rest>\S.*)$")
_KEYWORD_CLAUSE = re.compile(
    r"^(?P<token>(?:Abschnitt|Ziffer|Anforderung|Kriterium)\s+\d{1,3}(?:\.\d{1,2})*)"
    r"\s+(?P<rest>\S.*)$"
)
_ALPHA_CRITERION = re.compile(r"^(?P<token>[A-Z]{1,3}-\d{1,4})\s+(?P<rest>\S.*)$")


@dataclass(frozen=True, slots=True)
class StructuralIdentifier:
    """A recognized clause/criterion identifier and the text after it."""

    token: str
    remainder: str


def _dotted_number_is_plausible(token: str) -> bool:
    """Guard dotted numbers against dates, amounts, and IP addresses.

    Clause numbering uses short, small parts without leading zeros.
    Rejected deterministically: any part with a leading zero (dates such
    as ``24.08.2026``), any part above 99 (years, thousands separators
    such as ``1.500``), and four-part identifiers with any part above 9
    (IP addresses such as ``10.1.2.3`` while ``1.2.3.4`` stays a valid
    clause depth).
    """
    parts = re.findall(r"\d+", token)
    for part in parts:
        if len(part) > 1 and part.startswith("0"):
            return False
        if int(part) > 99:
            return False
    return not (len(parts) >= 4 and any(int(part) > 9 for part in parts))


def structural_identifier(text: str) -> StructuralIdentifier | None:
    """The structural identifier opening this block, or ``None``.

    A number alone is never an identifier: every accepted form requires
    following text on the same block.
    """
    for pattern in (_SECTION_SIGN, _KEYWORD_CLAUSE):
        match = pattern.match(text)
        if match is not None:
            return StructuralIdentifier(token=match.group("token"), remainder=match.group("rest"))
    match = _ALPHA_CRITERION.match(text)
    if match is not None:
        prefix = match.group("token").split("-", 1)[0]
        if prefix not in _EXCLUDED_ALPHA_PREFIXES:
            return StructuralIdentifier(token=match.group("token"), remainder=match.group("rest"))
        return None
    match = _DOTTED_NUMBER.match(text)
    if match is not None and _dotted_number_is_plausible(match.group("token")):
        return StructuralIdentifier(token=match.group("token"), remainder=match.group("rest"))
    return None


# ---------------------------------------------------------------------------
# Positive modality signals
# ---------------------------------------------------------------------------

#: Characters that end a sentence; auxiliary/infinitive pairs never cross one.
_IN_SENTENCE = r"[^.;:!?]"
#: A German infinitive at the end of its clause (``zu erstellen``,
#: ``zu verschlüsseln``, ``zu speichern``) — the next character must close
#: the clause so prepositional phrases such as ``zu diesen Zwecken`` never
#: count as obligations.
_CLAUSE_END = r"(?=\s*(?:[,.;:!?)]|und\b|oder\b|sowie\b|$))"
_INFINITIVE = r"[a-zäöüß]{3,}(?:en|eln|ern)\b" + _CLAUSE_END
_FUSED_INFINITIVE = r"[a-zäöüß]{2,}zu[a-zäöüß]{2,}(?:en|eln|ern)\b" + _CLAUSE_END

_MUST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:muss|müssen|must|shall)\b", re.IGNORECASE),
    re.compile(
        rf"\b(?:ist|sind|hat|haben)\b{_IN_SENTENCE}{{0,100}}?\bzu\s+{_INFINITIVE}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ist|sind|hat|haben)\b{_IN_SENTENCE}{{0,100}}?\b{_FUSED_INFINITIVE}",
        re.IGNORECASE,
    ),
)
_SHOULD_PATTERN = re.compile(r"\b(?:soll|sollen|should)\b", re.IGNORECASE)
_MAY_PATTERN = re.compile(r"\b(?:kann|können|may|optional)\b", re.IGNORECASE)


def modality_signal(text: str) -> RequirementModality | None:
    """The strongest positive modality signal in this text, or ``None``.

    Negation is deliberately not considered here; callers must check
    :func:`negation_signal` first.
    """
    if any(pattern.search(text) for pattern in _MUST_PATTERNS):
        return RequirementModality.MUST
    if _SHOULD_PATTERN.search(text):
        return RequirementModality.SHOULD
    if _MAY_PATTERN.search(text):
        return RequirementModality.MAY
    return None


# ---------------------------------------------------------------------------
# Negation / exclusion signals
# ---------------------------------------------------------------------------


class NegationKind(StrEnum):
    """How a block negates or excludes an obligation."""

    NO_OBLIGATION = "NO_OBLIGATION"
    PROHIBITION = "PROHIBITION"


_PROHIBITION_PATTERN = re.compile(
    rf"\b(?:darf|dürfen)\b{_IN_SENTENCE}{{0,80}}?\b(?:nicht|kein\w*)\b",
    re.IGNORECASE,
)
_NO_OBLIGATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:muss|müssen)\s+nicht\b", re.IGNORECASE),
    re.compile(r"\bnicht\s+erforderlich\b", re.IGNORECASE),
    re.compile(r"\bnicht\s+Bestandteil\b", re.IGNORECASE),
    re.compile(r"\bnicht\s+Gegenstand\b", re.IGNORECASE),
    re.compile(r"\baußerhalb\s+des\s+Leistungsumfangs\b", re.IGNORECASE),
    re.compile(r"\bnicht\s+zu\s+erbringen\b", re.IGNORECASE),
)


def negation_signal(text: str) -> NegationKind | None:
    """The explicit negation/exclusion signal in this text, or ``None``."""
    if _PROHIBITION_PATTERN.search(text):
        return NegationKind.PROHIBITION
    if any(pattern.search(text) for pattern in _NO_OBLIGATION_PATTERNS):
        return NegationKind.NO_OBLIGATION
    return None
