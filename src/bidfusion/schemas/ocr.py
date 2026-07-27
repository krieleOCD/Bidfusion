"""Provider-independent OCR request and normalized result contracts."""

from __future__ import annotations

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import BidfusionModel, Confidence
from bidfusion.schemas.ids import BidId, DocumentId
from bidfusion.schemas.provenance import SourceReference
from bidfusion.schemas.security import SecurityClearedArtifact


class OCRRequest(BidfusionModel):
    """Security-cleared content submitted through the owned OCR port."""

    source: SecurityClearedArtifact
    language_hints: list[str] = Field(default_factory=list)


class OCRBlock(BidfusionModel):
    """Normalized OCR text block suitable for canonical mapping."""

    block_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    text: str = Field(min_length=1)
    confidence: Confidence
    source: SourceReference


class OCRResult(BidfusionModel):
    """Normalized OCR output bound to its exact source and artifact lineage."""

    artifact: ArtifactEnvelope
    bid_id: BidId
    document_id: DocumentId
    source_artifact: ArtifactReference
    blocks: tuple[OCRBlock, ...]
    detected_language: str | None = Field(default=None, min_length=2)

    @model_validator(mode="after")
    def _result_is_traceable_and_canonical_ready(self) -> OCRResult:
        if self.artifact.artifact_type is not ArtifactType.OCR_RESULT:
            msg = "OCR results must use artifact_type ocr_result"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.source_artifact.bid_id != self.bid_id:
            msg = "OCR result artifacts must belong to the result bid"
            raise ValueError(msg)
        if self.source_artifact not in self.artifact.input_artifacts:
            msg = "OCR artifact lineage must include the exact source artifact"
            raise ValueError(msg)
        if self.source_artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "OCR input must reference a raw_document artifact"
            raise ValueError(msg)
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            msg = "OCR block IDs must be unique"
            raise ValueError(msg)
        orders = [block.order for block in self.blocks]
        if len(orders) != len(set(orders)):
            msg = "OCR block order values must be unique"
            raise ValueError(msg)
        for block in self.blocks:
            source = block.source
            if source.bid_id != self.bid_id or source.document_id != self.document_id:
                msg = "OCR block sources must identify the result bid and document"
                raise ValueError(msg)
            if source.document_hash != self.source_artifact.content_hash:
                msg = "OCR block sources must bind to the source artifact hash"
                raise ValueError(msg)
            if source.canonical_artifact_id is not None:
                msg = "OCR blocks precede canonical mapping"
                raise ValueError(msg)
            if source.locator.block_id != block.block_id or source.locator.page is None:
                msg = "OCR blocks require matching block and page locators"
                raise ValueError(msg)
        return self
