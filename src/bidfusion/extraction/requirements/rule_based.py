"""Deterministic rule-based requirement extraction over canonical documents.

v0.1 rule (unchanged, always applied first): a requirement candidate is a
paragraph of the form ``REQ-<label>: <text>`` or a table row containing a
``REQ-<label>`` cell.

v0.2 adds bounded label-free rule families for structured procurement
language (numbered/§ clauses with modality signals, criterion/question
structures, contractual party obligations, and structured table rows) —
see :mod:`.label_free` and :mod:`.signals`. Explicit labels keep their
v0.1 identifiers and ordering; label-free detections are appended after
them, and one source occurrence is never emitted twice.

Modality comes from explicit keyword matches; a candidate without a
modality keyword is honestly reported as ``UNKNOWN`` with low confidence
instead of being guessed, and explicitly negated statements are never
emitted as positive obligations.
"""

from __future__ import annotations

import re
from datetime import datetime

from bidfusion.extraction.requirements.label_free import (
    RuleFamily,
    assemble_blocks,
    classify_block,
    classify_row,
)
from bidfusion.extraction.support import (
    RowUnit,
    TextUnit,
    paragraph_units,
    row_units,
    seal_extraction_result,
)
from bidfusion.schemas.common import (
    ProcessingStatus,
    RequirementCategory,
    RequirementModality,
)
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.extraction import Requirement, RequirementExtractionResult
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.provenance import ExtractionInfo, SourceReference

REQUIREMENT_EXTRACTOR_NAME = "bidfusion-rule-requirement-extractor"
REQUIREMENT_EXTRACTOR_VERSION = "0.2.0"

_PARAGRAPH_CANDIDATE = re.compile(r"^(REQ-[A-Za-z0-9]+)\s*:\s*(?P<text>.+)$")
_LABEL_CELL = re.compile(r"^REQ-[A-Za-z0-9]+$")
_MODALITY_PATTERNS: tuple[tuple[RequirementModality, re.Pattern[str]], ...] = (
    (RequirementModality.MUST, re.compile(r"\b(must|shall|muss)\b", re.IGNORECASE)),
    (RequirementModality.SHOULD, re.compile(r"\b(should|soll)\b", re.IGNORECASE)),
    (RequirementModality.MAY, re.compile(r"\b(may|kann|optional)\b", re.IGNORECASE)),
)
_MODALITY_CELL_VALUES = {
    "must": RequirementModality.MUST,
    "shall": RequirementModality.MUST,
    "muss": RequirementModality.MUST,
    "should": RequirementModality.SHOULD,
    "soll": RequirementModality.SHOULD,
    "may": RequirementModality.MAY,
    "kann": RequirementModality.MAY,
    "optional": RequirementModality.MAY,
}
_CATEGORY_RULES: tuple[tuple[RequirementCategory, re.Pattern[str]], ...] = (
    (
        RequirementCategory.SECURITY,
        re.compile(r"security|encrypt|vulnerab|iso 27001|soc\b", re.IGNORECASE),
    ),
    (
        RequirementCategory.SUBMISSION,
        re.compile(r"submit|submission|portal|signature", re.IGNORECASE),
    ),
    (
        RequirementCategory.SERVICE,
        re.compile(r"service|sla|support|review", re.IGNORECASE),
    ),
)

_EXPLICIT_CONFIDENCE = 0.9
_UNCLEAR_CONFIDENCE = 0.4


def _paragraph_key(document: CanonicalDocument, unit: TextUnit) -> tuple[object, ...]:
    locator = unit.source.locator
    return (document.document_id, "paragraph", locator.page, locator.paragraph_id)


def _row_key(document: CanonicalDocument, row: RowUnit) -> tuple[object, ...]:
    return (
        document.document_id,
        "row",
        tuple(
            (
                cell.source.locator.table_id,
                cell.source.locator.row,
                cell.source.locator.column,
                cell.source.locator.cell_id,
            )
            for cell in row.cells
        ),
    )


def extract_requirements(
    documents: tuple[CanonicalDocument, ...],
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_id: ArtifactId,
    created_at: datetime,
) -> RequirementExtractionResult:
    """Extract requirement candidates from every provided canonical document.

    Pass 1 is the unchanged v0.1 explicit ``REQ-<label>`` rule, so explicit
    labels keep their identifiers and ordering. Pass 2 applies the bounded
    label-free rule families to every source occurrence pass 1 did not
    already claim.
    """
    requirements: list[Requirement] = []
    claimed: set[tuple[object, ...]] = set()
    for document in documents:
        for unit in paragraph_units(document):
            match = _PARAGRAPH_CANDIDATE.match(unit.text)
            if match is None:
                continue
            claimed.add(_paragraph_key(document, unit))
            requirements.append(
                _requirement(
                    bid_id=bid_id,
                    sequence=len(requirements) + 1,
                    original_text=unit.text,
                    normalized_text=match.group("text").strip(),
                    modality=_modality_from_text(match.group("text")),
                    unit=unit,
                )
            )
        for row in row_units(document):
            if not any(_LABEL_CELL.match(cell.text) for cell in row.cells):
                continue
            text_unit = _requirement_text_cell(row.cells)
            if text_unit is None:
                continue
            claimed.add(_row_key(document, row))
            requirements.append(
                _requirement(
                    bid_id=bid_id,
                    sequence=len(requirements) + 1,
                    original_text=text_unit.text,
                    normalized_text=text_unit.text,
                    modality=_row_modality(row.cells, text_unit),
                    unit=text_unit,
                )
            )

    for document in documents:
        for block in assemble_blocks(paragraph_units(document)):
            if any(_paragraph_key(document, unit) in claimed for unit in block.units):
                continue
            detection = classify_block(block.text)
            if detection is None:
                continue
            requirements.append(
                _requirement(
                    bid_id=bid_id,
                    sequence=len(requirements) + 1,
                    original_text=block.text,
                    normalized_text=detection.normalized_text,
                    modality=detection.modality,
                    unit=block.units[0],
                    additional_sources=tuple(unit.source for unit in block.units[1:]),
                    family=detection.family,
                    confidence=detection.confidence,
                )
            )
        for row in row_units(document):
            if _row_key(document, row) in claimed:
                continue
            row_detection = classify_row(tuple(cell.text for cell in row.cells))
            if row_detection is None:
                continue
            text_unit = row.cells[row_detection.text_cell_index]
            requirements.append(
                _requirement(
                    bid_id=bid_id,
                    sequence=len(requirements) + 1,
                    original_text=text_unit.text,
                    normalized_text=row_detection.normalized_text,
                    modality=row_detection.modality,
                    unit=text_unit,
                    family=row_detection.family,
                    confidence=row_detection.confidence,
                )
            )

    items = tuple(requirements)
    return seal_extraction_result(
        lambda envelope: RequirementExtractionResult(
            artifact=envelope,
            bid_id=bid_id,
            agent_name=REQUIREMENT_EXTRACTOR_NAME,
            agent_version=REQUIREMENT_EXTRACTOR_VERSION,
            document_ids=tuple(document.document_id for document in documents),
            status=ProcessingStatus.COMPLETED,
            started_at=created_at,
            finished_at=created_at,
            requirements=items,
        ),
        stream_name="requirement",
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        producer_component=REQUIREMENT_EXTRACTOR_NAME,
        producer_version=REQUIREMENT_EXTRACTOR_VERSION,
        documents=documents,
        created_at=created_at,
    )


def _requirement(
    *,
    bid_id: BidId,
    sequence: int,
    original_text: str,
    normalized_text: str,
    modality: RequirementModality,
    unit: TextUnit,
    additional_sources: tuple[SourceReference, ...] = (),
    family: RuleFamily | None = None,
    confidence: float | None = None,
) -> Requirement:
    """Build one requirement record.

    Without a ``family`` this is the unchanged v0.1 explicit-label shape
    (``method="rule"``, v0.1 confidence rules). Label-free detections carry
    their rule family in the extraction method (``rule/<family>``) and
    their own deterministic confidence.
    """
    if confidence is None:
        confidence = (
            _UNCLEAR_CONFIDENCE if modality is RequirementModality.UNKNOWN else _EXPLICIT_CONFIDENCE
        )
    return Requirement(
        requirement_id=f"REQ-{sequence:06d}",
        bid_id=bid_id,
        original_text=original_text,
        normalized_text=normalized_text or original_text,
        modality=modality,
        category=_category_for(family, normalized_text or original_text),
        confidence=confidence,
        source=unit.source,
        additional_sources=additional_sources,
        extraction=ExtractionInfo(
            method="rule" if family is None else f"rule/{family.value}",
            producer=REQUIREMENT_EXTRACTOR_NAME,
            producer_version=REQUIREMENT_EXTRACTOR_VERSION,
        ),
    )


def _category_for(family: RuleFamily | None, text: str) -> RequirementCategory:
    """v0.1 keyword categories, with one bounded refinement per new family."""
    category = _category_from_text(text)
    if category is RequirementCategory.TECHNICAL and family is RuleFamily.CONTRACTUAL_OBLIGATION:
        return RequirementCategory.CONTRACTUAL
    return category


def _modality_from_text(text: str) -> RequirementModality:
    for modality, pattern in _MODALITY_PATTERNS:
        if pattern.search(text):
            return modality
    return RequirementModality.UNKNOWN


def _row_modality(
    cells: tuple[TextUnit, ...],
    text_unit: TextUnit,
) -> RequirementModality:
    for cell in cells:
        explicit = _MODALITY_CELL_VALUES.get(cell.text.strip().lower())
        if explicit is not None:
            return explicit
    return _modality_from_text(text_unit.text)


def _requirement_text_cell(cells: tuple[TextUnit, ...]) -> TextUnit | None:
    candidates = [
        cell
        for cell in cells
        if not _LABEL_CELL.match(cell.text)
        and cell.text.strip().lower() not in _MODALITY_CELL_VALUES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda cell: len(cell.text))


def _category_from_text(text: str) -> RequirementCategory:
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return category
    return RequirementCategory.TECHNICAL
