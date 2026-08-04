"""Deterministic rule-based deadline extraction over canonical documents.

Recognizes ISO (``2026-09-30``, optionally with ``HH:MM``) and German
(``30.09.2026``) date formats in paragraphs and table rows. Date-only
values are normalized to 00:00 UTC by convention; the MVP performs no
timezone inference.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from bidfusion.extraction.support import (
    TextUnit,
    paragraph_units,
    row_units,
    seal_extraction_result,
)
from bidfusion.schemas.common import ProcessingStatus
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.extraction import Deadline, DeadlineExtractionResult, DeadlineKind
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.provenance import ExtractionInfo

DEADLINE_EXTRACTOR_NAME = "bidfusion-rule-deadline-extractor"
DEADLINE_EXTRACTOR_VERSION = "0.1.0"

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?")
_GERMAN_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_KIND_RULES: tuple[tuple[DeadlineKind, re.Pattern[str]], ...] = (
    (DeadlineKind.SUBMISSION, re.compile(r"submission|abgabe|einreich", re.IGNORECASE)),
    (DeadlineKind.QA, re.compile(r"q&a|question|frage", re.IGNORECASE)),
    (DeadlineKind.PRESENTATION, re.compile(r"presentation|präsentation", re.IGNORECASE)),
    (
        DeadlineKind.CONTRACT_START,
        re.compile(r"contract start|vertragsbeginn", re.IGNORECASE),
    ),
)
_CONFIDENCE = 0.8


def extract_deadlines(
    documents: tuple[CanonicalDocument, ...],
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_id: ArtifactId,
    created_at: datetime,
) -> DeadlineExtractionResult:
    """Extract dated deadlines from every provided canonical document."""
    deadlines: list[Deadline] = []
    for document in documents:
        for unit in paragraph_units(document):
            due_at = _first_date(unit.text)
            if due_at is None:
                continue
            deadlines.append(
                _deadline(
                    bid_id=bid_id,
                    sequence=len(deadlines) + 1,
                    due_at=due_at,
                    description=unit.text,
                    unit=unit,
                )
            )
        for row in row_units(document):
            date_unit = next(
                (cell for cell in row.cells if _first_date(cell.text) is not None),
                None,
            )
            if date_unit is None:
                continue
            due_at = _first_date(date_unit.text)
            if due_at is None:  # pragma: no cover - guarded by the search above
                continue
            description = " ".join(cell.text for cell in row.cells if cell is not date_unit).strip()
            deadlines.append(
                _deadline(
                    bid_id=bid_id,
                    sequence=len(deadlines) + 1,
                    due_at=due_at,
                    description=description or date_unit.text,
                    unit=date_unit,
                )
            )

    items = tuple(deadlines)
    return seal_extraction_result(
        lambda envelope: DeadlineExtractionResult(
            artifact=envelope,
            bid_id=bid_id,
            agent_name=DEADLINE_EXTRACTOR_NAME,
            agent_version=DEADLINE_EXTRACTOR_VERSION,
            document_ids=tuple(document.document_id for document in documents),
            status=ProcessingStatus.COMPLETED,
            started_at=created_at,
            finished_at=created_at,
            deadlines=items,
        ),
        stream_name="deadline",
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        producer_component=DEADLINE_EXTRACTOR_NAME,
        producer_version=DEADLINE_EXTRACTOR_VERSION,
        documents=documents,
        created_at=created_at,
    )


def _deadline(
    *,
    bid_id: BidId,
    sequence: int,
    due_at: datetime,
    description: str,
    unit: TextUnit,
) -> Deadline:
    return Deadline(
        deadline_id=f"DL-{sequence:03d}",
        bid_id=bid_id,
        kind=_kind_from_text(description),
        due_at=due_at,
        description=description,
        source=unit.source,
        confidence=_CONFIDENCE,
        extraction=ExtractionInfo(
            method="rule",
            producer=DEADLINE_EXTRACTOR_NAME,
            producer_version=DEADLINE_EXTRACTOR_VERSION,
        ),
    )


def first_date_candidate(text: str) -> datetime | None:
    """First recognizable date in ``text``, or ``None``.

    Public counterpart of the internal matching rule so coverage accounting
    uses exactly the extractor's own candidate definition.
    """
    return _first_date(text)


def _first_date(text: str) -> datetime | None:
    iso = _ISO_DATE.search(text)
    if iso is not None:
        year, month, day, hour, minute = iso.groups()
        try:
            return datetime(
                int(year),
                int(month),
                int(day),
                int(hour) if hour else 0,
                int(minute) if minute else 0,
                tzinfo=UTC,
            )
        except ValueError:
            return None
    german = _GERMAN_DATE.search(text)
    if german is not None:
        day, month, year = german.groups()
        try:
            return datetime(int(year), int(month), int(day), tzinfo=UTC)
        except ValueError:
            return None
    return None


def _kind_from_text(text: str) -> DeadlineKind:
    for kind, pattern in _KIND_RULES:
        if pattern.search(text):
            return kind
    return DeadlineKind.OTHER
