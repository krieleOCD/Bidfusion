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
    PERFORMATIVE_OBLIGATION = "performative-obligation"
    MODAL_STATEMENT = "modal-statement"
    LIST_SERVICE_ITEM = "list-service-item"
    PRICED_POSITION = "priced-position"
    EXCLUSION_CONDITION = "exclusion-condition"
    PROCEDURE_STATEMENT = "procedure-statement"


#: Deterministic per-detection confidence; families with an explicit
#: positive modality signal score higher than structure-only criteria,
#: and negated blocks stay at or below the v0.1 "unclear" level.
CONFIDENCE_MODAL = 0.75
CONFIDENCE_TABLE_MODALITY_CELL = 0.8
CONFIDENCE_PERFORMATIVE = 0.65
CONFIDENCE_MODAL_STATEMENT = 0.65
CONFIDENCE_CRITERION = 0.6
CONFIDENCE_LIST_ITEM = 0.55
CONFIDENCE_NO_OBLIGATION = 0.5
CONFIDENCE_PROHIBITION = 0.4

_MAX_BLOCK_UNITS = 12
_MAX_BLOCK_CHARS = 1200
_TERMINAL_PUNCTUATION = (".", ":", ";", "!", "?")
#: Characters that end a sentence; pattern windows never cross one.
_IN_SENTENCE = r"[^.;:!?]"

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
#: The contractor abbreviation ``AN`` counts only in an unambiguous definite
#: case form (``der/des/dem/den/vom AN``, ``durch den AN``); the capitals and
#: the article keep the German preposition ``an`` out.
_AN_REFERENCE = r"(?:\b(?:[Dd]er|[Dd]es|[Dd]em|[Dd]en|vom|durch\s+den)\s+AN\b)"
_PARTY_MENTION = re.compile(rf"\b{_OBLIGATED_PARTY}\b|{_AN_REFERENCE}")
_OBLIGATION_VERBS = re.compile(
    r"\b(?:ist\s+verpflichtet|verpflichtet\s+sich|stellt\s+sicher|sichert\s+zu"
    r"|gew(?:ä|ae)hrleistet|garantiert|haftet)\b",
    re.IGNORECASE,
)

#: Bounded performative-present vocabulary of general tender language: what a
#: contractor DOES as a commitment ("erbringt", "betreibt", "stellt ... zur
#: Verfügung"). Third-person singular forms only — past forms ("wurde",
#: "gegründet") and infinitives never match, so company history stays out.
_PERFORMATIVE_VERBS = (
    r"(?:erbringt|gew(?:ä|ae)hrt|betreibt|liefert|(?:ü|ue)bernimmt|erstellt|f(?:ü|ue)hrt"
    r"|pflegt|dokumentiert|unterst(?:ü|ue)tzt|(?:ü|ue)berwacht|meldet|informiert|benennt"
    r"|erarbeitet|verantwortet|bereitet|trifft|richtet|setzt|h(?:ä|ae)lt|stellt|weist"
    r"|sorgt|koordiniert|organisiert|plant|pr(?:ü|ue)ft|analysiert|bewertet|behebt"
    r"|implementiert|konfiguriert|schult|protokolliert|berichtet|archiviert|l(?:ö|oe)scht)"
)
#: Contractor as grammatical subject (nominative): the definite article plus
#: the contractor noun or its ``AN`` abbreviation. Dative/other case forms
#: ("dem AN", "stellt dem AN bereit") stay recipients, never subjects.
_CONTRACTOR_SUBJECT = r"(?:[Dd]er\s+(?:AN|Auftragnehmer)\b|[Dd]ie\s+Auftragnehmerin\b)"
_CONTRACTOR_AGENT = r"(?:(?:durch\s+den|vom)\s+(?:AN|Auftragnehmer)\b)"
_PERFORMATIVE_SUBJECT_VERB = re.compile(
    rf"{_CONTRACTOR_SUBJECT}\s+(?:{_PERFORMATIVE_VERBS}|wird|werden)\b"
)
_PERFORMATIVE_INVERSION = re.compile(rf"\b{_PERFORMATIVE_VERBS}\s+{_CONTRACTOR_SUBJECT}")
_PASSIVE_CONTRACTOR_AGENT = re.compile(
    rf"\b(?:wird|werden|erfolgt|erfolgen)\b{_IN_SENTENCE}{{0,120}}?{_CONTRACTOR_AGENT}"
    rf"|{_CONTRACTOR_AGENT}{_IN_SENTENCE}{{0,120}}?\b(?:wird|werden|erfolgt|erfolgen)\b"
)


def _mentions_party(text: str) -> bool:
    """Whether the text names one of the bounded obligated parties."""
    return _PARTY_MENTION.search(text) is not None


def normative_sentence_signal(text: str) -> bool:
    """Whether one sentence independently carries a strong obligation signal.

    Used by the v0.4 atomic splitter to decide sentence-level atomicity.
    Only binding language qualifies: MUST/SHOULD modality, an explicit
    prohibition, a party-obligation verb, or a performative contractor
    commitment. Possibility ("kann"), advisory notes, and no-obligation
    statements never open an atomic child of their own.
    """
    negation = negation_signal(text)
    if negation is NegationKind.PROHIBITION:
        return True
    if negation is NegationKind.NO_OBLIGATION:
        return False
    if modality_signal(text) in (RequirementModality.MUST, RequirementModality.SHOULD):
        return True
    return _OBLIGATION_VERBS.search(text) is not None or _performative_obligation(text)


def refine_modality(
    text: str,
    *,
    fallback_modality: RequirementModality,
    fallback_confidence: float,
) -> tuple[RequirementModality, float]:
    """Modality of one atomic child: its own bounded signal, else the parent's."""
    signal = _modality_and_confidence(text, base_confidence=fallback_confidence)
    return signal if signal is not None else (fallback_modality, fallback_confidence)


def _party_obligation_structure(text: str) -> bool:
    """Bounded contractual structure: obligated party plus obligation verb."""
    return (
        _mentions_party(text)
        and _OBLIGATION_VERBS.search(text) is not None
        and negation_signal(text) is None
    )


def _performative_obligation(text: str) -> bool:
    """Bounded performative structure: the contractor commits by doing.

    Three grammatical shapes of general tender language qualify: contractor
    subject followed by a performative-present or future verb ("Der AN
    erbringt ...", "Der Auftragnehmer wird ... ausführen"), verb-first
    inversion ("Auf Anforderung stellt der AN ..."), and passive voice with
    an explicit contractor agent ("... werden durch den AN gepflegt.").
    """
    return (
        _PERFORMATIVE_SUBJECT_VERB.search(text) is not None
        or _PERFORMATIVE_INVERSION.search(text) is not None
        or _PASSIVE_CONTRACTOR_AGENT.search(text) is not None
    ) and negation_signal(text) is None


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


#: Table-of-contents dot leaders ("Einführung ...... 3"); such lines are
#: navigation, never requirements, whatever vocabulary they contain.
_DOT_LEADER = re.compile(r"\.{4,}")

#: Bounded list-marker characters that open service/deliverable items.
_BULLET_SPLIT = re.compile(r"[◼▪•●‣○]")
#: German action-noun morphology for a list item's first word: nominalized
#: activities ("Bereitstellung", "Aufnahme", "Analyse", "Reporting",
#: "Mitwirkungspflichten") — never brand or product names.
_ACTION_NOUN = re.compile(
    r"^[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]*"
    r"(?:ung|ungen|ion|ionen|nahme|nahmen|yse|ysen|abe|aben|ing|ings"
    r"|management|pflicht|pflichten|transfer)$"
)
#: Small closed set of bare activity words that carry no suffix.
_ACTION_WORDS = frozenset({"Test", "Design", "Vorgehen", "Betrieb"})
#: Passive/impersonal specification verbs inside a bulleted item.
_LIST_PASSIVE = re.compile(r"\b(?:wird|werden|erfolgt|erfolgen)\b")
#: Trailing contractor assignment of a responsibility-matrix row.
_TRAILING_ASSIGNMENT = re.compile(r"\sAN(?:\s+AG)?\s*$")

#: A catalogue position code inside flattened table text: letters-first,
#: hyphen-segmented, ending in a numeric segment ("SO-ITSec-001"). Standard
#: and identifier references (ISO-27001, CVE-...) never qualify.
_POSITION_CODE_TOKEN = re.compile(r"\b([A-Za-z]{2,5})(?:-[A-Za-z0-9]{1,12}){1,2}-\d{1,6}\b")
_NON_POSITION_PREFIXES = frozenset({"REQ", "CVE", "ISO", "EN", "DIN", "BSI"})


#: Binding invalidity/exclusion formalities of a tender procedure: what is
#: not admissible, not considered, without effect, or grounds for exclusion.
_EXCLUSION_PATTERNS: tuple[str, ...] = (
    r"\b(?:ist|sind)\s+nicht\s+zul(?:ä|ae)ssig\b",
    r"\b(?:ist|sind)\s+nicht\s+zugelassen\b",
    r"\b(?:ist|sind)\s+unzul(?:ä|ae)ssig\b",
    r"\b(?:wird|werden)\s+nicht\s+ber(?:ü|ue)cksichtigt\b",
    r"\bfinden?\s+keine\s+Anwendung\b",
    r"\bf(?:ü|ue)hr(?:t|en)\s+zum\s+Ausschluss\b",
    r"\b(?:wird|werden)\s+(?:vom\s+Verfahren\s+)?ausgeschlossen\b",
    r"\bnicht\s+(?:mehr\s+)?geltend\s+gemacht\s+werden\b",
)
_EXCLUSION_CONDITION = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _EXCLUSION_PATTERNS)


#: Binding procedure/legal statements of the award process and contract
#: mechanics: awarding-entity future commitments, reservation clauses, and
#: bounded constraint participles.
_AWARDING_ENTITY_FUTURE = re.compile(
    r"\b[Dd](?:er\s+Auftraggeber|ie\s+Auftraggeberin|ie\s+Vergabestelle)\s+(?:wird|werden)\b"
)
_RESERVATION_CLAUSE = re.compile(
    rf"\bbeh(?:ä|ae)lt\s+sich\b{_IN_SENTENCE}{{0,80}}?\bvor\b", re.IGNORECASE
)
_CONSTRAINT_PARTICIPLE = re.compile(
    rf"\b(?:ist|sind)\b{_IN_SENTENCE}{{0,120}}?\b(?:beschr(?:ä|ae)nkt|begrenzt|untersagt)\b",
    re.IGNORECASE,
)
_PROCEDURE_PASSIVE = re.compile(r"\b(?:wird|werden|erfolgt|erfolgen)\b")


def _procedure_statement(text: str, *, has_identifier: bool) -> BlockDetection | None:
    """A binding award-process or contract-mechanics statement, if any.

    Passive/impersonal process verbs count only under a structural
    identifier; free-floating background prose never qualifies.
    """
    qualified = (
        _AWARDING_ENTITY_FUTURE.search(text) is not None
        or _RESERVATION_CLAUSE.search(text) is not None
        or _CONSTRAINT_PARTICIPLE.search(text) is not None
        or (has_identifier and _PROCEDURE_PASSIVE.search(text) is not None)
    )
    if not qualified:
        return None
    return BlockDetection(
        family=RuleFamily.PROCEDURE_STATEMENT,
        modality=RequirementModality.UNKNOWN,
        confidence=CONFIDENCE_LIST_ITEM,
        normalized_text=text,
    )


def _exclusion_condition(text: str) -> BlockDetection | None:
    """A binding negative formality of the procedure, if any."""
    if not any(pattern.search(text) for pattern in _EXCLUSION_CONDITION):
        return None
    return BlockDetection(
        family=RuleFamily.EXCLUSION_CONDITION,
        modality=RequirementModality.UNKNOWN,
        confidence=CONFIDENCE_CRITERION,
        normalized_text=text,
    )


def _position_code_in_text(text: str) -> bool:
    return any(
        match.group(1).upper() not in _NON_POSITION_PREFIXES
        for match in _POSITION_CODE_TOKEN.finditer(text)
    )


def _action_noun_start(segment: str) -> bool:
    words = segment.split()
    if len(words) < 2:
        return False
    first = words[0].strip(",.;:")
    return _ACTION_NOUN.match(first) is not None or first in _ACTION_WORDS


def _structural_fallback(
    text: str, *, require_bullet: bool, has_identifier: bool = False
) -> BlockDetection | None:
    """Fallback families applied when no primary language family fired."""
    exclusion = _exclusion_condition(text)
    if exclusion is not None:
        return exclusion
    procedure = _procedure_statement(text, has_identifier=has_identifier)
    if procedure is not None:
        return procedure
    if _position_code_in_text(text) and len(text.split()) >= 4:
        return BlockDetection(
            family=RuleFamily.PRICED_POSITION,
            modality=RequirementModality.UNKNOWN,
            confidence=CONFIDENCE_LIST_ITEM,
            normalized_text=text,
        )
    return _list_service_item(text, require_bullet=require_bullet)


def _list_service_item(text: str, *, require_bullet: bool) -> BlockDetection | None:
    """Bulleted service/deliverable items and activity-assignment rows.

    Structure alone never qualifies: a bulleted segment must open with an
    action noun, or the bulleted text must carry a passive specification
    verb; a bullet-less row qualifies only as an action-noun activity with
    a trailing contractor assignment marker.
    """
    segments = _BULLET_SPLIT.split(text)
    has_bullet = len(segments) > 1
    if has_bullet:
        items = [segment.strip() for segment in segments[1:]]
        qualified = any(_action_noun_start(item) for item in items) or (
            _LIST_PASSIVE.search(text) is not None
        )
    elif require_bullet:
        return None
    else:
        qualified = _action_noun_start(text) and _TRAILING_ASSIGNMENT.search(text) is not None
    if not qualified or negation_signal(text) is not None:
        return None
    return BlockDetection(
        family=RuleFamily.LIST_SERVICE_ITEM,
        modality=RequirementModality.UNKNOWN,
        confidence=CONFIDENCE_LIST_ITEM,
        normalized_text=text,
    )


def classify_block(text: str) -> BlockDetection | None:
    """Classify one clause block into a label-free rule family, if any."""
    stripped = text.strip()
    if not stripped or _EXPLICIT_LABEL_START.match(stripped):
        return None
    if _DOT_LEADER.search(stripped):
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
        if _performative_obligation(remainder):
            return BlockDetection(
                family=RuleFamily.PERFORMATIVE_OBLIGATION,
                modality=RequirementModality.MUST,
                confidence=CONFIDENCE_PERFORMATIVE,
                normalized_text=remainder,
            )
        # a heading alone never qualifies, so items need their bullet here
        return _structural_fallback(remainder, require_bullet=True, has_identifier=True)

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
        if _performative_obligation(stripped):
            return BlockDetection(
                family=RuleFamily.PERFORMATIVE_OBLIGATION,
                modality=RequirementModality.MUST,
                confidence=CONFIDENCE_PERFORMATIVE,
                normalized_text=stripped,
            )
        return _structural_fallback(stripped, require_bullet=False)

    # plain prose with a normative modality signal but neither identifier
    # nor party; a bare possibility (MAY) without an obligated party stays
    # out, and very short fragments are never a requirement clause
    signal = _modality_and_confidence(stripped, base_confidence=CONFIDENCE_MODAL_STATEMENT)
    if signal is not None and len(stripped.split()) >= 4:
        modality, confidence = signal
        if modality is not RequirementModality.MAY:
            return BlockDetection(
                family=RuleFamily.MODAL_STATEMENT,
                modality=modality,
                confidence=confidence,
                normalized_text=stripped,
            )
    return _structural_fallback(stripped, require_bullet=False)


_LABEL_CELL = re.compile(r"^REQ-[A-Za-z0-9]+$")
_ROW_TOTAL_WORDS = frozenset({"summe", "gesamt", "gesamtsumme", "zwischensumme", "total"})
_IDENTIFIER_CELL = re.compile(
    r"^(?:[A-Z]{1,3}-\d{1,4}|\d{1,3}(?:\.\d{1,2})*\.?|Kriterium\s+\d{1,3})$"
)

#: Letters-first, hyphen-segmented position codes of service catalogues and
#: price sheets ("SO-ITSec-001"). Single-letter-prefix criterion codes stay
#: with the structured-table family; REQ/CVE prefixes never qualify.
_POSITION_CODE_CELL = re.compile(r"^[A-Za-z]{2,5}(?:-[A-Za-z0-9]{1,12}){1,3}$")

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

    position_cells = [
        index
        for index, cell in enumerate(stripped)
        if _POSITION_CODE_CELL.match(cell) and cell.split("-", 1)[0].upper() not in ("REQ", "CVE")
    ]
    if position_cells:
        described = [
            index
            for index, cell in enumerate(stripped)
            if index not in position_cells and _has_letters(cell) and len(cell.split()) >= 2
        ]
        if described:
            text_index = max(described, key=lambda index: len(stripped[index]))
            return RowDetection(
                family=RuleFamily.PRICED_POSITION,
                modality=RequirementModality.UNKNOWN,
                confidence=CONFIDENCE_CRITERION,
                text_cell_index=text_index,
                normalized_text=stripped[text_index],
            )

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
