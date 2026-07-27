"""Strict source locators and extraction metadata for end-to-end provenance."""

from __future__ import annotations

from pydantic import Field, model_validator

from bidfusion.schemas.common import (
    BidfusionModel,
    SemanticVersion,
    Sha256Digest,
)
from bidfusion.schemas.ids import ArtifactId, BidId, DocumentId


class TextSpan(BidfusionModel):
    """Half-open character range in canonical text."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _end_follows_start(self) -> TextSpan:
        if self.end <= self.start:
            msg = "text span end must be greater than start"
            raise ValueError(msg)
        return self


class BoundingBox(BidfusionModel):
    """OCR or vision bounding box in the producer's declared coordinate space."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    coordinate_space: str = Field(
        default="source",
        description='Producer-defined space, e.g. "pixels", "points", or "normalized".',
    )


class SourceLocator(BidfusionModel):
    """Typed location within a source; at least one locator is required."""

    whole_document: bool = False
    page: int | None = Field(default=None, ge=1)
    section_id: str | None = Field(default=None, min_length=1)
    block_id: str | None = Field(default=None, min_length=1)
    paragraph_id: str | None = Field(default=None, min_length=1)
    table_id: str | None = Field(default=None, min_length=1)
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    cell_id: str | None = Field(default=None, min_length=1)
    text_span: TextSpan | None = None
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def _has_a_location(self) -> SourceLocator:
        located = self.whole_document or any(
            value is not None
            for value in (
                self.page,
                self.section_id,
                self.block_id,
                self.paragraph_id,
                self.table_id,
                self.row,
                self.column,
                self.cell_id,
                self.text_span,
                self.bounding_box,
            )
        )
        if not located:
            msg = "a source locator must identify a document location"
            raise ValueError(msg)
        return self


class SourceReference(BidfusionModel):
    """Pointer to exact original content and, when available, its canonical block."""

    bid_id: BidId
    document_id: DocumentId
    filename: str = Field(min_length=1)
    document_hash: Sha256Digest
    locator: SourceLocator
    canonical_artifact_id: ArtifactId | None = None
    quote: str | None = Field(default=None, min_length=1)


class ExtractionInfo(BidfusionModel):
    """How a source-derived fact was produced."""

    method: str = Field(min_length=1, description='e.g. "llm", "rule", "hybrid", "human"')
    producer: str = Field(min_length=1)
    producer_version: SemanticVersion
    model: str | None = Field(
        default=None,
        description="Gateway-assigned model identifier; business modules do not select providers.",
    )
    prompt_version: str | None = None
