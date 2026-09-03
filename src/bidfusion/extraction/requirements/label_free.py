"""Label-free rule families of the deterministic requirement extractor v0.2.

Families are bounded and independently testable:

- ``NUMBERED_MODAL_REQUIREMENT``: structural identifier + modality signal;
- ``CRITERION_OR_QUESTION``: criterion/question structure (identifier plus
  question mark or bounded criterion vocabulary, or an explicit criterion
  marker opening the block);
- ``CONTRACTUAL_OBLIGATION``: bounded party-obligation phrasing without a
  structural identifier;
- ``STRUCTURED_TABLE_REQUIREMENT``: bounded requirement/criterion rows in
  parsed tables.

Detection never fires on a number alone, on facts/sizing statements, or on
narrative prose without structural evidence. Classification is pure text
work; canonical wiring lives in :mod:`.rule_based`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from bidfusion.extraction.requirements.signals import (
    NegationKind,
    modality_signal,
    negation_signal,
    structural_identifier,
)
from bidfusion.extraction.support import TextUnit
from bidfusion.schemas.common import RequirementModality


class RuleFamily(StrEnum):
    """Which bounded detection rule produced a requirement candidate."""

    EXPLICIT_LABEL = "explicit-label"
    NUMBERED_MODAL_REQUIREMENT = "numbered-modal"
    CRITERION_OR_QUESTION = "criterion-or-question"
    CONTRACTUAL_OBLIGATION = "contractual-obligation"
    STRUCTURED_TABLE_REQUIREMENT = "structured-table"


#: Deterministic per-detection confidence; families with an explicit
#: positive modality signal score higher than structure-only criteria,
#: and negated blocks stay at or below the v0.1 "unclear" level.
CONFIDENCE_MODAL = 0.75
CONFIDENCE_TABLE_MODALITY_CELL = 0.8
CONFIDENCE_CRITERION = 0.6
CONFIDENCE_NO_OBLIGATION = 0.5
CONFIDENCE_PROHIBITION = 0.4

_MAX_BLOCK_UNITS = 6
_MAX_BLOCK_CHARS = 600
_TERMINAL_PUNCTUATION = (".", ":", ";", "!", "?")

_EXPLICIT_LABEL_START = re.compile(r"^REQ-[A-Za-z0-9]+\s*:")

_CRITERION_MARKER_START = re.compile(
    r"^(?:Ausschlusskriterium|Zuschlagskriterium|Bewertungskriterium|Eignungskriterium"
    r"|Mindestanforderung|Mindestkriterium)\b[\s:]",
    re.IGNORECASE,
)
_CRITERION_VOCABULARY = re.compile(
    r"\b(?:Ausschlusskriterium|Zuschlagskriterium|Bewertungskriterium|Eignungskriterium"
    r"|Mindestanforderung|Mindestkriterium|Nachweis\w*|Eigenerkl(?:ä|ae)rung\w*"
    r"|Erkl(?:ä|ae)rung\w*|Best(?:ä|ae)tigung\w*|best(?:ä|ae)tigt|Formblatt\w*"
    r"|vorzulegen|beizuf(?:ü|ue)gen|einzureichen|nachzuweisen"
    r"|ausgeschlossen|Ausschluss\w*)\b",
    re.IGNORECASE,
)

_OBLIGATED_PARTY = (
    r"(?:Auftragnehmer(?:in)?|Bieter(?:in)?|Bewerber(?:in)?|Dienstleister"
    r"|Lieferant(?:en|in)?|Anbieter)"
)
_PARTY_MENTION = re.compile(rf"\b{_OBLIGATED_PARTY}\b")
_OBLIGATION_VERBS = re.compile(
    r"\b(?:ist\s+verpflichtet|verpflichtet\s+sich|stellt\s+sicher|sichert\s+zu"
    r"|gew(?:ä|ae)hrleistet|garantiert|haftet)\b",
    re.IGNORECASE,
)


def _mentions_party(text: str) -> bool:
    """Whether the text names one of the bounded obligated parties."""
    return _PARTY_MENTION.search(text) is not None


def _party_obligation_structure(text: str) -> bool:
    """Bounded contractual structure: obligated party plus obligation verb."""
    return (
        _mentions_party(text)
        and _OBLIGATION_VERBS.search(text) is not None
        and negation_signal(text) is None
    )


@dataclass(frozen=True, slots=True)
class ClauseBlock:
    """Adjacent canonical lines of one page, joined into one clause."""

    units: tuple[TextUnit, ...]

    @property
    def text(self) -> str:
        return " ".join(unit.text for unit in self.units)


@dataclass(frozen=True, slots=True)
class BlockDetection:
    """One label-free paragraph/block detection."""

    family: RuleFamily
    modality: RequirementModality
    confidence: float
    normalized_text: str


@dataclass(frozen=True, slots=True)
class RowDetection:
    """One label-free table-row detection."""

    family: RuleFamily
    modality: RequirementModality
    confidence: float
    text_cell_index: int
    normalized_text: str


def assemble_blocks(units: Sequence[TextUnit]) -> tuple[ClauseBlock, ...]:
    """Join adjacent same-page line paragraphs into bounded clause blocks.

    A new block starts on a page change, on a structural identifier or an
    explicit ``REQ-`` label, after a line ending in terminal punctuation,
    or when the bounded block size is reached. Blocks never span pages or
    tables, and every joined line keeps its own provenance unit.
    """
    blocks: list[ClauseBlock] = []
    current: list[TextUnit] = []

    def close() -> None:
        if current:
            blocks.append(ClauseBlock(units=tuple(current)))
            current.clear()

    for unit in units:
        text = unit.text.strip()
        if not text:
            close()
            continue
        starts_new = (
            structural_identifier(text) is not None or _EXPLICIT_LABEL_START.match(text) is not None
        )
        if current:
            same_page = current[-1].source.locator.page == unit.source.locator.page
            over_budget = (
                len(current) >= _MAX_BLOCK_UNITS
                or sum(len(item.text) for item in current) >= _MAX_BLOCK_CHARS
            )
            if starts_new or not same_page or over_budget:
                close()
        current.append(unit)
        if text.endswith(_TERMINAL_PUNCTUATION):
            close()
    close()
    return tuple(blocks)


def _modality_and_confidence(
    text: str, *, base_confidence: float
) -> tuple[RequirementModality, float] | None:
    """Map negation/modality signals to the existing modality taxonomy.

    Explicit negation is checked first and never becomes a positive
    obligation: no-obligation statements are ``INFORMATIONAL``; explicit
    prohibitions cannot be represented by the positive taxonomy and are
    honestly reported as ``UNKNOWN`` with low confidence.
    """
    negation = negation_signal(text)
    if negation is NegationKind.NO_OBLIGATION:
        return RequirementModality.INFORMATIONAL, CONFIDENCE_NO_OBLIGATION
    if negation is NegationKind.PROHIBITION:
        return RequirementModality.UNKNOWN, CONFIDENCE_PROHIBITION
    modality = modality_signal(text)
    if modality is None:
        return None
    return modality, base_confidence


def classify_block(text: str) -> BlockDetection | None:
    """Classify one clause block into a label-free rule family, if any."""
    stripped = text.strip()
    if not stripped or _EXPLICIT_LABEL_START.match(stripped):
        return None
    identifier = structural_identifier(stripped)
    remainder = identifier.remainder if identifier is not None else stripped

    # a criterion needs a clause, not a bare heading: "2. Nachweise" is a
    # section title even though it carries a criterion keyword
    criterion_clause = len(remainder.split()) >= 4
    if _CRITERION_MARKER_START.match(stripped) or (
        identifier is not None
        and criterion_clause
        and (remainder.endswith("?") or _CRITERION_VOCABULARY.search(remainder))
    ):
        signal = _modality_and_confidence(remainder, base_confidence=CONFIDENCE_MODAL)
        modality, confidence = (
            signal
            if signal
            else (
                RequirementModality.UNKNOWN,
                CONFIDENCE_CRITERION,
            )
        )
        return BlockDetection(
            family=RuleFamily.CRITERION_OR_QUESTION,
            modality=modality,
            confidence=confidence,
            normalized_text=remainder,
        )

    if identifier is not None:
        signal = _modality_and_confidence(remainder, base_confidence=CONFIDENCE_MODAL)
        if signal is not None:
            modality, confidence = signal
            # a bare "kann/optional" possibility is only an obligation when
            # an obligated party carries it; reference prose such as
            # "können dem Anhang entnommen werden" never qualifies
            if modality is RequirementModality.MAY and not _mentions_party(remainder):
                return None
            return BlockDetection(
                family=RuleFamily.NUMBERED_MODAL_REQUIREMENT,
                modality=modality,
                confidence=confidence,
                normalized_text=remainder,
            )
        if _party_obligation_structure(remainder):
            return BlockDetection(
                family=RuleFamily.CONTRACTUAL_OBLIGATION,
                modality=RequirementModality.MUST,
                confidence=CONFIDENCE_MODAL,
                normalized_text=remainder,
            )
        return None

    if _mentions_party(stripped):
        if _OBLIGATION_VERBS.search(stripped) and negation_signal(stripped) is None:
            return BlockDetection(
                family=RuleFamily.CONTRACTUAL_OBLIGATION,
                modality=RequirementModality.MUST,
                confidence=CONFIDENCE_MODAL,
                normalized_text=stripped,
            )
        signal = _modality_and_confidence(stripped, base_confidence=CONFIDENCE_MODAL)
        if signal is not None:
            modality, confidence = signal
            return BlockDetection(
                family=RuleFamily.CONTRACTUAL_OBLIGATION,
                modality=modality,
                confidence=confidence,
                normalized_text=stripped,
            )
    return None


_LABEL_CELL = re.compile(r"^REQ-[A-Za-z0-9]+$")
_ROW_TOTAL_WORDS = frozenset({"summe", "gesamt", "gesamtsumme", "zwischensumme", "total"})
_IDENTIFIER_CELL = re.compile(
    r"^(?:[A-Z]{1,3}-\d{1,4}|\d{1,3}(?:\.\d{1,2})*\.?|Kriterium\s+\d{1,3})$"
)

#: v0.1 modality cell vocabulary, kept identical for compatibility.
_MODALITY_CELL_VALUES: dict[str, RequirementModality] = {
    "must": RequirementModality.MUST,
    "shall": RequirementModality.MUST,
    "muss": RequirementModality.MUST,
    "should": RequirementModality.SHOULD,
    "soll": RequirementModality.SHOULD,
    "may": RequirementModality.MAY,
    "kann": RequirementModality.MAY,
    "optional": RequirementModality.MAY,
}


def _has_letters(text: str) -> bool:
    return any(character.isalpha() for character in text)


def classify_row(cells: Sequence[str]) -> RowDetection | None:
    """Classify one table row into the structured-table family, if any.

    Header rows, totals, price-only rows, sizing/quantity rows, purely
    numeric rows, and blank rows never qualify. Cells are never
    concatenated: the detection points at exactly one text cell.
    """
    stripped = tuple(cell.strip() for cell in cells)
    if not any(stripped):
        return None
    first = stripped[0].lower().rstrip(".:")
    if first in _ROW_TOTAL_WORDS:
        return None
    if any(_LABEL_CELL.match(cell) for cell in stripped):
        return None

    modality_cell = next(
        (
            _MODALITY_CELL_VALUES[cell.lower()]
            for cell in stripped
            if cell.lower() in _MODALITY_CELL_VALUES
        ),
        None,
    )
    text_candidates = [
        index
        for index, cell in enumerate(stripped)
        if cell
        and cell.lower() not in _MODALITY_CELL_VALUES
        and _has_letters(cell)
        and len(cell.split()) >= 3
    ]
    if not text_candidates:
        return None
    text_index = max(text_candidates, key=lambda index: len(stripped[index]))
    text = stripped[text_index]
    has_identifier_cell = any(
        _IDENTIFIER_CELL.match(cell) and cell.split("-", 1)[0] not in ("REQ", "CVE")
        for index, cell in enumerate(stripped)
        if index != text_index and cell
    )

    signal = _modality_and_confidence(text, base_confidence=CONFIDENCE_MODAL)
    if signal is not None:
        modality, confidence = signal
        return RowDetection(
            family=RuleFamily.STRUCTURED_TABLE_REQUIREMENT,
            modality=modality,
            confidence=confidence,
            text_cell_index=text_index,
            normalized_text=text,
        )
    if modality_cell is not None:
        return RowDetection(
            family=RuleFamily.STRUCTURED_TABLE_REQUIREMENT,
            modality=modality_cell,
            confidence=CONFIDENCE_TABLE_MODALITY_CELL,
            text_cell_index=text_index,
            normalized_text=text,
        )
    if has_identifier_cell and (text.endswith("?") or _CRITERION_VOCABULARY.search(text)):
        return RowDetection(
            family=RuleFamily.STRUCTURED_TABLE_REQUIREMENT,
            modality=RequirementModality.UNKNOWN,
            confidence=CONFIDENCE_CRITERION,
            text_cell_index=text_index,
            normalized_text=text,
        )
    return None
