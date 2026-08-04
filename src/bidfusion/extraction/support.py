"""Shared helpers for the deterministic rule-based extraction slice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.provenance import SourceReference
from bidfusion.shared.payloads import EnvelopedArtifact, seal_artifact

EXTRACTION_SCHEMA_VERSION = "1.0.0"


def extraction_domain(stream_name: str) -> str:
    """Domain discriminator for one extraction stream's hash projection."""
    return f"extraction/{stream_name}"


def extraction_content_ref(stream_name: str) -> str:
    """Canonical payload location for one extraction stream."""
    return f"extraction/{stream_name}-extraction.payload.json"


@dataclass(frozen=True, slots=True)
class TextUnit:
    """One canonical text block with its exact provenance."""

    text: str
    source: SourceReference


@dataclass(frozen=True, slots=True)
class RowUnit:
    """One canonical table row as ordered text cells with provenance."""

    cells: tuple[TextUnit, ...]


def paragraph_units(document: CanonicalDocument) -> tuple[TextUnit, ...]:
    """All paragraphs of a canonical document, in reading order."""
    return tuple(
        TextUnit(text=paragraph.text, source=paragraph.source)
        for page in document.pages
        for paragraph in page.paragraphs
    )


def row_units(document: CanonicalDocument) -> tuple[RowUnit, ...]:
    """All table rows of a canonical document, in sheet and row order."""
    return tuple(
        RowUnit(cells=tuple(TextUnit(text=cell.text, source=cell.source) for cell in row.cells))
        for page in document.pages
        for table in page.tables
        for row in table.rows
    )


def cell_units(document: CanonicalDocument) -> tuple[TextUnit, ...]:
    """All table cells of a canonical document, in reading order."""
    return tuple(cell for row in row_units(document) for cell in row.cells)


def seal_extraction_result[ResultT: EnvelopedArtifact](
    build: Callable[[ArtifactEnvelope], ResultT],
    *,
    stream_name: str,
    artifact_id: ArtifactId,
    bid_id: BidId,
    run_id: RunId,
    producer_component: str,
    producer_version: str,
    documents: tuple[CanonicalDocument, ...],
    created_at: datetime,
) -> ResultT:
    """Seal one extraction result under the shared hash convention."""
    return seal_artifact(
        build,
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version=EXTRACTION_SCHEMA_VERSION,
        domain=extraction_domain(stream_name),
        content_ref=extraction_content_ref(stream_name),
        producer_component=producer_component,
        producer_version=producer_version,
        input_artifacts=canonical_input_references(documents),
        created_at=created_at,
    )


def canonical_input_references(
    documents: tuple[CanonicalDocument, ...],
) -> tuple[ArtifactReference, ...]:
    """Immutable references to the canonical artifacts behind an extraction."""
    return tuple(document.artifact.as_reference() for document in documents)
