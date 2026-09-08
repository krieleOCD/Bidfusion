"""Versioned pipeline artifact and lineage contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.common import (
    BidfusionModel,
    SemanticVersion,
    Sha256Digest,
)
from bidfusion.schemas.ids import ArtifactId, BidId, RunId


class ArtifactType(StrEnum):
    """Stable artifact kinds represented by Foundation contracts."""

    RAW_DOCUMENT = "raw_document"
    OCR_RESULT = "ocr_result"
    CANONICAL_DOCUMENT = "canonical_document"
    EXTRACTION_RESULT = "extraction_result"
    NORMALIZED_BID_DATASET = "normalized_bid_dataset"
    COMPLIANCE_MATRIX = "compliance_matrix"
    WORKING_PACKAGE = "working_package"
    REVIEWED_WORKING_PACKAGE = "reviewed_working_package"
    UPLOAD_MANIFEST = "upload_manifest"
    BID_RUN_RECORD = "bid_run_record"


class ArtifactProducer(BidfusionModel):
    """Component and version that produced an artifact."""

    component: str = Field(min_length=1)
    version: SemanticVersion


class ArtifactReference(BidfusionModel):
    """Immutable reference to exact artifact content."""

    artifact_id: ArtifactId
    bid_id: BidId
    run_id: RunId
    artifact_type: ArtifactType
    schema_version: SemanticVersion
    content_ref: str = Field(min_length=1)
    content_hash: Sha256Digest


class ArtifactEnvelope(ArtifactReference):
    """First-class pipeline artifact metadata with transformation lineage."""

    producer: ArtifactProducer
    input_artifacts: tuple[ArtifactReference, ...] = Field(default_factory=tuple)
    created_at: datetime

    @model_validator(mode="after")
    def _lineage_is_bid_isolated(self) -> ArtifactEnvelope:
        input_ids = [input_artifact.artifact_id for input_artifact in self.input_artifacts]
        if len(input_ids) != len(set(input_ids)):
            msg = "artifact input lineage cannot contain duplicate artifact IDs"
            raise ValueError(msg)
        for input_artifact in self.input_artifacts:
            if input_artifact.bid_id != self.bid_id:
                msg = "input artifacts must belong to the envelope bid"
                raise ValueError(msg)
            if input_artifact.artifact_id == self.artifact_id:
                msg = "an artifact cannot reference itself as an input"
                raise ValueError(msg)
        return self

    def as_reference(self) -> ArtifactReference:
        """Return the immutable reference portion of this envelope."""
        return ArtifactReference.model_validate(
            self.model_dump(
                include={
                    "artifact_id",
                    "bid_id",
                    "run_id",
                    "artifact_type",
                    "schema_version",
                    "content_ref",
                    "content_hash",
                }
            )
        )
