"""Registered files, inventory entries, and the provenance-rich canonical model."""

from __future__ import annotations

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import (
    BidfusionModel,
    Confidence,
    DataClassification,
    ProcessingStatus,
    SecurityVerdict,
    Sha256Digest,
)
from bidfusion.schemas.ids import BidId, DocumentId
from bidfusion.schemas.provenance import SourceReference


class Document(BidfusionModel):
    """A raw, immutable file registered with a bid package."""

    document_id: DocumentId
    bid_id: BidId
    artifact: ArtifactReference
    filename: str = Field(min_length=1)
    file_type: str = Field(min_length=1, description="Normalized type, e.g. pdf, docx, xlsx")
    mime_type: str = Field(min_length=1)
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    parent_document_id: DocumentId | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _artifact_matches_document(self) -> Document:
        if self.artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "registered documents must reference raw_document artifacts"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id:
            msg = "document and artifact must belong to the same bid"
            raise ValueError(msg)
        if self.artifact.content_hash != self.sha256:
            msg = "document hash must match its artifact reference"
            raise ValueError(msg)
        return self


class DocumentInventoryEntry(BidfusionModel):
    """Inventory record of a received document (Domain C)."""

    bid_id: BidId
    document_id: DocumentId
    artifact: ArtifactReference
    filename: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    hash: Sha256Digest
    size: int = Field(ge=0, description="File size in bytes")
    page_count: int | None = Field(default=None, ge=0)
    language: str | None = None
    security_status: SecurityVerdict
    classification: DataClassification = DataClassification.CONFIDENTIAL
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    parent_document: DocumentId | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _artifact_matches_inventory(self) -> DocumentInventoryEntry:
        if self.artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "inventory entries must reference raw_document artifacts"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.artifact.content_hash != self.hash:
            msg = "inventory entry must reference the same bid and exact content hash"
            raise ValueError(msg)
        downstream_processing = {
            ProcessingStatus.IN_PROGRESS,
            ProcessingStatus.COMPLETED,
        }
        if (
            self.security_status
            in {
                SecurityVerdict.BLOCK,
                SecurityVerdict.QUARANTINE,
                SecurityVerdict.MANUAL_REVIEW,
            }
            and self.processing_status in downstream_processing
        ):
            msg = (
                f"{self.security_status.value} security status cannot have downstream "
                f"processing status {self.processing_status.value}"
            )
            raise ValueError(msg)
        if (
            self.security_status in {SecurityVerdict.BLOCK, SecurityVerdict.QUARANTINE}
            and self.processing_status is ProcessingStatus.REQUIRES_REVIEW
        ):
            msg = "BLOCK and QUARANTINE are terminal and cannot require downstream review"
            raise ValueError(msg)
        return self


class Paragraph(BidfusionModel):
    """A paragraph with stable identity, order, hierarchy, and provenance."""

    paragraph_id: str = Field(min_length=1)
    text: str
    order: int = Field(ge=0)
    section_id: str | None = Field(default=None, min_length=1)
    source: SourceReference


class TableCell(BidfusionModel):
    """A table cell, including merged-cell spans and exact provenance."""

    cell_id: str = Field(min_length=1)
    text: str
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    source: SourceReference


class TableRow(BidfusionModel):
    """A row in a canonical table."""

    row_number: int = Field(ge=1)
    cells: tuple[TableCell, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _cells_belong_to_row(self) -> TableRow:
        if any(cell.row != self.row_number for cell in self.cells):
            msg = "all cells in a table row must use that row number"
            raise ValueError(msg)
        return self


class Table(BidfusionModel):
    """A structured source table."""

    table_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    section_id: str | None = Field(default=None, min_length=1)
    caption: str | None = None
    rows: tuple[TableRow, ...] = Field(default_factory=tuple)
    source: SourceReference


class Figure(BidfusionModel):
    """A figure, image, drawing, or diagram."""

    figure_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    section_id: str | None = Field(default=None, min_length=1)
    caption: str | None = None
    kind: str | None = None
    description: str | None = None
    source: SourceReference


class Footnote(BidfusionModel):
    """A source-derived footnote or endnote."""

    footnote_id: str = Field(min_length=1)
    marker: str | None = None
    text: str
    source: SourceReference


class Section(BidfusionModel):
    """A section node whose parent ID preserves document hierarchy."""

    section_id: str = Field(min_length=1)
    title: str
    level: int = Field(default=1, ge=1)
    order: int = Field(ge=0)
    parent_section_id: str | None = Field(default=None, min_length=1)
    source: SourceReference


class Page(BidfusionModel):
    """One page of canonical source-derived blocks."""

    page_number: int = Field(ge=1)
    sections: tuple[Section, ...] = Field(default_factory=tuple)
    paragraphs: tuple[Paragraph, ...] = Field(default_factory=tuple)
    tables: tuple[Table, ...] = Field(default_factory=tuple)
    figures: tuple[Figure, ...] = Field(default_factory=tuple)
    footnotes: tuple[Footnote, ...] = Field(default_factory=tuple)
    ocr_applied: bool = False
    ocr_confidence: Confidence | None = None

    @model_validator(mode="after")
    def _ocr_confidence_is_coherent(self) -> Page:
        if not self.ocr_applied and self.ocr_confidence is not None:
            msg = "ocr_confidence is only valid when OCR was applied"
            raise ValueError(msg)
        return self


class DocumentRelationship(BidfusionModel):
    """A typed relationship between two documents of the same bid."""

    bid_id: BidId
    from_document_id: DocumentId
    to_document_id: DocumentId
    kind: str = Field(min_length=1)


class DocumentMetadata(BidfusionModel):
    """Technical metadata of a canonical document."""

    title: str | None = None
    language: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)


class CanonicalDocument(BidfusionModel):
    """Structured output created from a ``SecurityClearedArtifact`` input."""

    artifact: ArtifactEnvelope
    source_artifact: ArtifactReference
    document_id: DocumentId
    bid_id: BidId
    metadata: DocumentMetadata
    pages: tuple[Page, ...] = Field(default_factory=tuple)
    relationships: tuple[DocumentRelationship, ...] = Field(default_factory=tuple)
    source: SourceReference

    @model_validator(mode="after")
    def _lineage_and_block_provenance_are_coherent(self) -> CanonicalDocument:
        if self.artifact.artifact_type is not ArtifactType.CANONICAL_DOCUMENT:
            msg = "canonical documents require a canonical_document artifact"
            raise ValueError(msg)
        if self.source_artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "canonical documents must originate from a raw_document artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.source_artifact.bid_id != self.bid_id:
            msg = "canonical and source artifacts must belong to the document bid"
            raise ValueError(msg)
        if self.source.bid_id != self.bid_id or self.source.document_id != self.document_id:
            msg = "canonical document source must reference the original document"
            raise ValueError(msg)
        if self.source.document_hash != self.source_artifact.content_hash:
            msg = "canonical source hash must match the original artifact"
            raise ValueError(msg)
        input_ids = {item.artifact_id for item in self.artifact.input_artifacts}
        if self.source_artifact.artifact_id not in input_ids:
            msg = "canonical artifact lineage must include its source artifact"
            raise ValueError(msg)
        if any(relationship.bid_id != self.bid_id for relationship in self.relationships):
            msg = "document relationships must belong to the canonical document bid"
            raise ValueError(msg)

        all_sections = [section for page in self.pages for section in page.sections]
        section_ids = {section.section_id for section in all_sections}
        if len(section_ids) != len(all_sections):
            msg = "section IDs must be unique within a canonical document"
            raise ValueError(msg)
        if self.metadata.page_count is not None and self.metadata.page_count != len(self.pages):
            msg = "canonical metadata page_count must match the page collection"
            raise ValueError(msg)
        located_blocks: list[tuple[SourceReference, int, str, str]] = []
        located_cells: list[tuple[SourceReference, int, TableCell]] = []
        for page in self.pages:
            located_blocks.extend(
                (section.source, page.page_number, "section_id", section.section_id)
                for section in page.sections
            )
            located_blocks.extend(
                (
                    paragraph.source,
                    page.page_number,
                    "paragraph_id",
                    paragraph.paragraph_id,
                )
                for paragraph in page.paragraphs
            )
            located_blocks.extend(
                (table.source, page.page_number, "table_id", table.table_id)
                for table in page.tables
            )
            located_blocks.extend(
                (figure.source, page.page_number, "block_id", figure.figure_id)
                for figure in page.figures
            )
            located_blocks.extend(
                (footnote.source, page.page_number, "block_id", footnote.footnote_id)
                for footnote in page.footnotes
            )
            located_cells.extend(
                (cell.source, page.page_number, cell)
                for table in page.tables
                for row in table.rows
                for cell in row.cells
            )
            section_refs = [
                *(paragraph.section_id for paragraph in page.paragraphs),
                *(table.section_id for table in page.tables),
                *(figure.section_id for figure in page.figures),
            ]
            section_refs = [section_id for section_id in section_refs if section_id]
            if any(section_id not in section_ids for section_id in section_refs):
                msg = "canonical blocks must reference an existing section"
                raise ValueError(msg)

        for section in all_sections:
            if (
                section.parent_section_id is not None
                and section.parent_section_id not in section_ids
            ):
                msg = "parent_section_id must reference an existing section"
                raise ValueError(msg)
        for source, page_number, locator_field, block_id in located_blocks:
            if source.bid_id != self.bid_id or source.document_id != self.document_id:
                msg = "canonical blocks must reference their original document"
                raise ValueError(msg)
            if source.document_hash != self.source_artifact.content_hash:
                msg = "canonical block source hash must match the original artifact"
                raise ValueError(msg)
            if source.canonical_artifact_id != self.artifact.artifact_id:
                msg = "canonical blocks must bind provenance to the canonical artifact"
                raise ValueError(msg)
            if source.locator.page != page_number:
                msg = "canonical block provenance page must match its containing page"
                raise ValueError(msg)
            if getattr(source.locator, locator_field) != block_id:
                msg = "canonical block provenance must identify the exact block ID"
                raise ValueError(msg)
        for source, page_number, cell in located_cells:
            if (
                source.bid_id != self.bid_id
                or source.document_id != self.document_id
                or source.document_hash != self.source_artifact.content_hash
                or source.canonical_artifact_id != self.artifact.artifact_id
            ):
                msg = "canonical cells must bind to their source artifact and document"
                raise ValueError(msg)
            locator = source.locator
            if (
                locator.page != page_number
                or locator.cell_id != cell.cell_id
                or locator.row != cell.row
                or locator.column != cell.column
            ):
                msg = "canonical cell provenance must identify the exact page, row, and column"
                raise ValueError(msg)
        return self
