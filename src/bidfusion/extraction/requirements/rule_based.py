"""Deterministic rule-based requirement extraction over canonical documents.

MVP rule: a requirement candidate is a paragraph of the form
``REQ-<label>: <text>`` or a table row containing a ``REQ-<label>`` cell.
Modality comes from explicit keyword matches; a candidate without a modality
keyword is honestly reported as ``UNKNOWN`` with low confidence instead of
being guessed.
"""

from __future__ import annotations

import re
from datetime import datetime

from bidfusion.extraction.support import (
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
from bidfusion.schemas.provenance import ExtractionInfo

REQUIREMENT_EXTRACTOR_NAME = "bidfusion-rule-requirement-extractor"
REQUIREMENT_EXTRACTOR_VERSION = "0.1.0"

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


def extract_requirements(
    documents: tuple[CanonicalDocument, ...],
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_id: ArtifactId,
    created_at: datetime,
) -> RequirementExtractionResult:
    """Extract requirement candidates from every provided canonical document."""
    requirements: list[Requirement] = []
    for document in documents:
        for unit in paragraph_units(document):
            match = _PARAGRAPH_CANDIDATE.match(unit.text)
            if match is None:
                continue
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
) -> Requirement:
    return Requirement(
        requirement_id=f"REQ-{sequence:06d}",
        bid_id=bid_id,
        original_text=original_text,
        normalized_text=normalized_text,
        modality=modality,
        category=_category_from_text(normalized_text),
        confidence=(
            _UNCLEAR_CONFIDENCE if modality is RequirementModality.UNKNOWN else _EXPLICIT_CONFIDENCE
        ),
        source=unit.source,
        extraction=ExtractionInfo(
            method="rule",
            producer=REQUIREMENT_EXTRACTOR_NAME,
            producer_version=REQUIREMENT_EXTRACTOR_VERSION,
        ),
    )


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
