"""Technical processing-run state, independent from the bid business lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel, ProcessingStatus
from bidfusion.schemas.ids import BidId, RunId


class ProcessingStage(StrEnum):
    """Current technical stage of a pipeline run."""

    RECEIVED = "RECEIVED"
    SECURITY_SCAN = "SECURITY_SCAN"
    INVENTORIED = "INVENTORIED"
    PARSED = "PARSED"
    STRUCTURED = "STRUCTURED"
    EXTRACTED = "EXTRACTED"
    NORMALIZED = "NORMALIZED"
    QA = "QA"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    WORKING_PACKAGE_READY = "WORKING_PACKAGE_READY"


class ProcessingRun(BidfusionModel):
    """Auditable status and produced artifacts for one technical run."""

    run_id: RunId
    bid_id: BidId
    stage: ProcessingStage
    status: ProcessingStatus
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    artifacts: tuple[ArtifactReference, ...] = Field(default_factory=tuple)
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _run_is_coherent(self) -> ProcessingRun:
        if self.updated_at < self.started_at:
            msg = "updated_at cannot precede started_at"
            raise ValueError(msg)
        if self.completed_at is not None and self.completed_at < self.started_at:
            msg = "completed_at cannot precede started_at"
            raise ValueError(msg)
        if self.status is ProcessingStatus.COMPLETED and self.completed_at is None:
            msg = "completed processing runs require completed_at"
            raise ValueError(msg)
        for artifact in self.artifacts:
            if artifact.bid_id != self.bid_id or artifact.run_id != self.run_id:
                msg = "run artifacts must carry the same bid_id and run_id"
                raise ValueError(msg)
        return self
