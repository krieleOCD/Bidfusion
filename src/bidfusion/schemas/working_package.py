"""Evidence-at-claim Bid Working Package contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import (
    BidfusionModel,
    FrozenDict,
    FrozenMapping,
    RequirementCategory,
    RequirementModality,
    Severity,
)
from bidfusion.schemas.extraction import Deadline
from bidfusion.schemas.ids import BidId, RequirementId
from bidfusion.schemas.provenance import SourceReference


class EvidencedStatement(BidfusionModel):
    """Important statement linked to normalized objects and original evidence."""

    text: str = Field(min_length=1)
    normalized_object_ids: tuple[str, ...] = Field(min_length=1)
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _normalized_links_are_unique(self) -> EvidencedStatement:
        if len(self.normalized_object_ids) != len(set(self.normalized_object_ids)):
            msg = "normalized object links on a statement must be unique"
            raise ValueError(msg)
        return self


class ExecutiveOverview(BidfusionModel):
    """Evidence-bearing executive summary of the bid opportunity."""

    customer: EvidencedStatement | None = None
    rfp_title: EvidencedStatement | None = None
    opportunity: EvidencedStatement | None = None
    scope_summary: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    objectives: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)


class SubmissionInstructions(BidfusionModel):
    """Evidence-bearing instructions extracted from the source package."""

    portal: EvidencedStatement | None = None
    upload_process: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    required_accounts: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    formats: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    naming_rules: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    signatures_required: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    file_size_limits: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)
    special_requirements: tuple[EvidencedStatement, ...] = Field(default_factory=tuple)


class RequirementsSummary(BidfusionModel):
    """Validated counts of normalized requirements."""

    total: int = Field(default=0, ge=0)
    by_modality: FrozenMapping[RequirementModality, int] = Field(default_factory=FrozenDict)
    by_category: FrozenMapping[RequirementCategory, int] = Field(default_factory=FrozenDict)

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> RequirementsSummary:
        if self.by_modality and sum(self.by_modality.values()) != self.total:
            msg = "requirement modality counts must sum to total"
            raise ValueError(msg)
        if self.by_category and sum(self.by_category.values()) != self.total:
            msg = "requirement category counts must sum to total"
            raise ValueError(msg)
        if any(count < 0 for count in (*self.by_modality.values(), *self.by_category.values())):
            msg = "requirement summary counts cannot be negative"
            raise ValueError(msg)
        return self


class Risk(BidfusionModel):
    """Evidence-bearing risk identified for the bid."""

    risk_id: str = Field(min_length=1)
    statement: EvidencedStatement
    category: str = Field(min_length=1)
    severity: Severity = Severity.MEDIUM


class OpenQuestion(BidfusionModel):
    """Evidence-bearing open issue or potential bidder clarification."""

    question_id: str = Field(min_length=1)
    statement: EvidencedStatement
    reason: str = Field(min_length=1)
    potential_clarification: bool = False


class WorkingPackage(BidfusionModel):
    """Human-facing package lineaged to one normalized dataset."""

    artifact: ArtifactEnvelope
    source_dataset: ArtifactReference
    bid_id: BidId
    version: int = Field(default=1, ge=1)
    generated_at: datetime
    executive_overview: ExecutiveOverview = Field(default_factory=ExecutiveOverview)
    timeline: tuple[Deadline, ...] = Field(default_factory=tuple)
    submission_instructions: SubmissionInstructions = Field(default_factory=SubmissionInstructions)
    requirements_summary: RequirementsSummary = Field(default_factory=RequirementsSummary)
    critical_requirements: tuple[RequirementId, ...] = Field(default_factory=tuple)
    risks: tuple[Risk, ...] = Field(default_factory=tuple)
    open_questions: tuple[OpenQuestion, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _package_is_bid_isolated_and_lineaged(self) -> WorkingPackage:
        if self.artifact.artifact_type is not ArtifactType.WORKING_PACKAGE:
            msg = "working packages require a working_package artifact"
            raise ValueError(msg)
        if self.source_dataset.artifact_type is not ArtifactType.NORMALIZED_BID_DATASET:
            msg = "working package source must be a normalized_bid_dataset"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.source_dataset.bid_id != self.bid_id:
            msg = "working package artifacts must belong to the package bid"
            raise ValueError(msg)
        input_ids = {item.artifact_id for item in self.artifact.input_artifacts}
        if self.source_dataset.artifact_id not in input_ids:
            msg = "working package lineage must include its normalized dataset"
            raise ValueError(msg)
        if any(deadline.bid_id != self.bid_id for deadline in self.timeline):
            msg = "working package deadlines must belong to the package bid"
            raise ValueError(msg)
        overview = self.executive_overview
        statements = [
            *(
                item
                for item in (overview.customer, overview.rfp_title, overview.opportunity)
                if item is not None
            ),
            *overview.scope_summary,
            *overview.objectives,
        ]
        submission = self.submission_instructions
        if submission.portal is not None:
            statements.append(submission.portal)
        statements.extend(submission.upload_process)
        statements.extend(submission.required_accounts)
        statements.extend(submission.formats)
        statements.extend(submission.naming_rules)
        statements.extend(submission.signatures_required)
        statements.extend(submission.file_size_limits)
        statements.extend(submission.special_requirements)
        statements.extend(risk.statement for risk in self.risks)
        statements.extend(question.statement for question in self.open_questions)
        if any(
            source.bid_id != self.bid_id for statement in statements for source in statement.sources
        ):
            msg = "working package claim evidence must belong to the package bid"
            raise ValueError(msg)
        return self
