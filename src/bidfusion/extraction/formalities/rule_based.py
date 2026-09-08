"""Deterministic rule-based formality extraction over canonical documents.

Ordered keyword rules classify submission-related obligations. Requirement
candidates (``REQ-…`` lines and cells) are excluded so one statement is not
double-classified by two streams.
"""

from __future__ import annotations

import re
from datetime import datetime

from bidfusion.extraction.support import (
    TextUnit,
    cell_units,
    paragraph_units,
    seal_extraction_result,
)
from bidfusion.schemas.common import ProcessingStatus
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.extraction import (
    Formality,
    FormalityExtractionResult,
    FormalityKind,
)
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.provenance import ExtractionInfo

FORMALITY_EXTRACTOR_NAME = "bidfusion-rule-formality-extractor"
FORMALITY_EXTRACTOR_VERSION = "0.1.0"

_REQUIREMENT_CANDIDATE = re.compile(r"^REQ-[A-Za-z0-9]+\b")
_KIND_RULES: tuple[tuple[FormalityKind, re.Pattern[str]], ...] = (
    (
        FormalityKind.SIGNATURE_REQUIREMENT,
        re.compile(r"\bsign(ed|ature)\b|unterschrift", re.IGNORECASE),
    ),
    (FormalityKind.PORTAL_REQUIREMENT, re.compile(r"\bportal\b", re.IGNORECASE)),
    (
        FormalityKind.REQUIRED_FORMAT,
        re.compile(r"\b(pdf|xlsx|docx)\s+format\b|\bas\s+(pdf|xlsx|docx)\b", re.IGNORECASE),
    ),
    (
        FormalityKind.SUBMISSION_INSTRUCTION,
        re.compile(r"must be submitted|submit via|late submission", re.IGNORECASE),
    ),
)
_CONFIDENCE = 0.8


def extract_formalities(
    documents: tuple[CanonicalDocument, ...],
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_id: ArtifactId,
    created_at: datetime,
) -> FormalityExtractionResult:
    """Extract submission formalities from every provided canonical document."""
    formalities: list[Formality] = []
    for document in documents:
        units = (*paragraph_units(document), *cell_units(document))
        for unit in units:
            if _REQUIREMENT_CANDIDATE.match(unit.text):
                continue
            kind = _kind_for(unit.text)
            if kind is None:
                continue
            formalities.append(
                _formality(
                    bid_id=bid_id,
                    sequence=len(formalities) + 1,
                    kind=kind,
                    unit=unit,
                )
            )

    items = tuple(formalities)
    return seal_extraction_result(
        lambda envelope: FormalityExtractionResult(
            artifact=envelope,
            bid_id=bid_id,
            agent_name=FORMALITY_EXTRACTOR_NAME,
            agent_version=FORMALITY_EXTRACTOR_VERSION,
            document_ids=tuple(document.document_id for document in documents),
            status=ProcessingStatus.COMPLETED,
            started_at=created_at,
            finished_at=created_at,
            formalities=items,
        ),
        stream_name="formality",
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        producer_component=FORMALITY_EXTRACTOR_NAME,
        producer_version=FORMALITY_EXTRACTOR_VERSION,
        documents=documents,
        created_at=created_at,
    )


def _formality(
    *,
    bid_id: BidId,
    sequence: int,
    kind: FormalityKind,
    unit: TextUnit,
) -> Formality:
    return Formality(
        formality_id=f"FORM-{sequence:03d}",
        bid_id=bid_id,
        kind=kind,
        original_text=unit.text,
        normalized_text=unit.text,
        source=unit.source,
        confidence=_CONFIDENCE,
        extraction=ExtractionInfo(
            method="rule",
            producer=FORMALITY_EXTRACTOR_NAME,
            producer_version=FORMALITY_EXTRACTOR_VERSION,
        ),
    )


def matches_formality_rule(text: str) -> bool:
    """True when ``text`` matches one of the extractor's own keyword rules.

    Public counterpart of the internal matching rule so coverage accounting
    uses exactly the extractor's own candidate definition. Requirement
    candidates (``REQ-…``) are excluded here as in the extractor.
    """
    return not _REQUIREMENT_CANDIDATE.match(text) and _kind_for(text) is not None


def _kind_for(text: str) -> FormalityKind | None:
    for kind, pattern in _KIND_RULES:
        if pattern.search(text):
            return kind
    return None
