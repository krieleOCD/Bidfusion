"""Bid workspace and business lifecycle, separate from technical processing."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel, DataClassification
from bidfusion.schemas.ids import BidId, OpportunityId


class BidBusinessState(StrEnum):
    """Minimal business lifecycle; technical stages live on ``ProcessingRun``."""

    QUALIFYING = "QUALIFYING"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"


class Bid(BidfusionModel):
    """A bid workspace related to one upstream commercial opportunity."""

    bid_id: BidId
    opportunity_id: OpportunityId
    title: str = Field(min_length=1)
    customer: str | None = None
    received_at: datetime
    classification: DataClassification = DataClassification.CONFIDENTIAL
    business_state: BidBusinessState = BidBusinessState.QUALIFYING
    source_package: ArtifactReference | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _source_package_is_bid_isolated(self) -> Bid:
        if self.source_package is not None and self.source_package.bid_id != self.bid_id:
            msg = "source package must belong to the bid"
            raise ValueError(msg)
        return self
