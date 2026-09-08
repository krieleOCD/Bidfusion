"""Measurable technical extraction coverage over canonical documents.

This module counts — it never scores. Every number is a technical count
over canonical text units (paragraphs and table rows) and the extractors'
own matching rules; there is no invented semantic accuracy.

Definitions:

- *Obligation candidate*: a unit that contains an obligation keyword
  (case-insensitive English ``MUST``/``SHALL``/``SHOULD``/``MAY`` or German
  ``muss``/``müssen``/``soll``/``sollen``/``sollte``/``sollten``/``kann``/
  ``können``) and is long enough to be a statement (bare modality cells are
  table attributes, not obligations). Table rows are counted as units.
- *Obligation match*: a candidate whose text was captured by the
  requirement or formality stream, or that carries an explicit ``REQ-``
  label (and is therefore accounted by the requirement extractor).
- *Unexplained candidate*: an obligation candidate with no such match.
- *Deadline/formality candidates and matches* use exactly the respective
  extractor's own candidate rule and captured results.
"""

from __future__ import annotations

import re

from pydantic import Field

from bidfusion.extraction.deadlines.rule_based import first_date_candidate
from bidfusion.extraction.formalities.rule_based import matches_formality_rule
from bidfusion.extraction.support import (
    RowUnit,
    cell_units,
    paragraph_units,
    row_units,
)
from bidfusion.schemas.common import BidfusionModel
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.extraction import (
    DeadlineExtractionResult,
    FormalityExtractionResult,
    RequirementExtractionResult,
)

#: Case-insensitive obligation keywords (English and German modal verbs).
OBLIGATION_KEYWORDS = re.compile(
    r"\b(?:must|shall|should|may|muss|müssen|soll|sollen|sollte|sollten|kann|können)\b",
    re.IGNORECASE,
)

#: A unit shorter than this is a bare modality attribute, not a statement.
MIN_OBLIGATION_STATEMENT_WORDS = 3

_REQUIREMENT_LABEL = re.compile(r"^REQ-[A-Za-z0-9]+\b")


class ExtractionCoverage(BidfusionModel):
    """Technical coverage counts of one extraction pass."""

    total_units_examined: int = Field(ge=0)
    obligation_candidates: int = Field(ge=0)
    obligation_matches: int = Field(ge=0)
    obligation_match_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    deadline_candidates: int = Field(ge=0)
    deadline_matches: int = Field(ge=0)
    unexplained_deadline_candidates: int = Field(ge=0)
    deadline_match_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    formality_candidates: int = Field(ge=0)
    formality_matches: int = Field(ge=0)
    unexplained_formality_candidates: int = Field(ge=0)
    formality_match_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    unexplained_candidates: int = Field(ge=0)


def compute_extraction_coverage(
    canonicals: tuple[CanonicalDocument, ...],
    *,
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
) -> ExtractionCoverage:
    """Count candidates and matches over every canonical text unit."""
    captured_texts = _captured_texts(requirements, formalities)
    formality_texts = _formality_texts(formalities)
    captured_due_ats = frozenset(
        item.due_at for item in (deadlines.deadlines if deadlines is not None else ())
    )

    total_units = 0
    obligation_candidates = 0
    obligation_matches = 0
    deadline_candidates = 0
    deadline_matches = 0
    formality_candidates = 0
    formality_matches = 0

    for canonical in canonicals:
        paragraphs = paragraph_units(canonical)
        rows = row_units(canonical)
        total_units += len(paragraphs) + len(rows)

        for unit in paragraphs:
            text = unit.text.strip()
            if _is_obligation_candidate(text):
                obligation_candidates += 1
                if _paragraph_is_explained(text, captured_texts):
                    obligation_matches += 1
            candidate_date = first_date_candidate(text)
            if candidate_date is not None:
                deadline_candidates += 1
                if candidate_date in captured_due_ats:
                    deadline_matches += 1

        for row in rows:
            joined = " ".join(cell.text.strip() for cell in row.cells).strip()
            if _is_obligation_candidate(joined):
                obligation_candidates += 1
                if _row_is_explained(row, captured_texts):
                    obligation_matches += 1
            row_date = next(
                (
                    date
                    for date in (first_date_candidate(cell.text) for cell in row.cells)
                    if date is not None
                ),
                None,
            )
            if row_date is not None:
                deadline_candidates += 1
                if row_date in captured_due_ats:
                    deadline_matches += 1

        for unit in (*paragraphs, *cell_units(canonical)):
            text = unit.text.strip()
            if not matches_formality_rule(text):
                continue
            formality_candidates += 1
            if text in formality_texts:
                formality_matches += 1

    return ExtractionCoverage(
        total_units_examined=total_units,
        obligation_candidates=obligation_candidates,
        obligation_matches=obligation_matches,
        obligation_match_ratio=_match_ratio(obligation_matches, obligation_candidates),
        deadline_candidates=deadline_candidates,
        deadline_matches=deadline_matches,
        unexplained_deadline_candidates=deadline_candidates - deadline_matches,
        deadline_match_ratio=_match_ratio(deadline_matches, deadline_candidates),
        formality_candidates=formality_candidates,
        formality_matches=formality_matches,
        unexplained_formality_candidates=formality_candidates - formality_matches,
        formality_match_ratio=_match_ratio(formality_matches, formality_candidates),
        unexplained_candidates=obligation_candidates - obligation_matches,
    )


def _match_ratio(matches: int, candidates: int) -> float | None:
    """Exact lexical match ratio, or ``None`` when there is no candidate."""
    return None if candidates == 0 else matches / candidates


def _is_obligation_candidate(text: str) -> bool:
    return (
        len(text.split()) >= MIN_OBLIGATION_STATEMENT_WORDS
        and OBLIGATION_KEYWORDS.search(text) is not None
    )


def _paragraph_is_explained(text: str, captured_texts: frozenset[str]) -> bool:
    return bool(_REQUIREMENT_LABEL.match(text)) or text in captured_texts


def _row_is_explained(row: RowUnit, captured_texts: frozenset[str]) -> bool:
    return any(
        _REQUIREMENT_LABEL.match(cell.text.strip()) or cell.text.strip() in captured_texts
        for cell in row.cells
    )


def _captured_texts(
    requirements: RequirementExtractionResult | None,
    formalities: FormalityExtractionResult | None,
) -> frozenset[str]:
    captured: set[str] = set()
    for requirement in requirements.requirements if requirements is not None else ():
        captured.add(requirement.original_text.strip())
        if requirement.normalized_text:
            captured.add(requirement.normalized_text.strip())
    captured |= _formality_texts(formalities)
    return frozenset(captured)


def _formality_texts(formalities: FormalityExtractionResult | None) -> frozenset[str]:
    captured: set[str] = set()
    for formality in formalities.formalities if formalities is not None else ():
        captured.add(formality.original_text.strip())
        if formality.normalized_text:
            captured.add(formality.normalized_text.strip())
    return frozenset(captured)
