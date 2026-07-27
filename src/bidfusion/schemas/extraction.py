"""Atomic business extraction contracts with mandatory canonical provenance."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactType
from bidfusion.schemas.common import (
    BidfusionModel,
    Confidence,
    ProcessingStatus,
    RequirementCategory,
    RequirementModality,
)
from bidfusion.schemas.ids import BidId, DocumentId, RequirementId
from bidfusion.schemas.provenance import ExtractionInfo, SourceReference


class Requirement(BidfusionModel):
    """A two-dimensional requirement with mandatory canonical evidence."""

    requirement_id: RequirementId
    bid_id: BidId
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    modality: RequirementModality
    category: RequirementCategory
    confidence: Confidence
    dependencies: tuple[RequirementId, ...] = Field(default_factory=tuple)
    cross_references: tuple[str, ...] = Field(default_factory=tuple)
    source: SourceReference
    additional_sources: tuple[SourceReference, ...] = Field(default_factory=tuple)
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> Requirement:
        if self.source.bid_id != self.bid_id:
            msg = "requirement source must belong to the requirement bid"
            raise ValueError(msg)
        if self.source.canonical_artifact_id is None:
            msg = "extracted requirements must reference a canonical artifact"
            raise ValueError(msg)
        for source in self.additional_sources:
            if source.bid_id != self.bid_id or source.canonical_artifact_id is None:
                msg = "additional requirement sources must be canonical and bid-isolated"
                raise ValueError(msg)
        return self

    @property
    def mandatory(self) -> bool:
        """Whether the requirement expresses a MUST obligation."""
        return self.modality is RequirementModality.MUST


class DeadlineKind(StrEnum):
    """Kinds of deadlines and milestones in a bid process."""

    SUBMISSION = "SUBMISSION"
    QA = "QA"
    PRESENTATION = "PRESENTATION"
    NEGOTIATION = "NEGOTIATION"
    CONTRACT_START = "CONTRACT_START"
    MILESTONE = "MILESTONE"
    OTHER = "OTHER"


class Deadline(BidfusionModel):
    """A deadline or milestone mentioned in the bid documents."""

    deadline_id: str = Field(min_length=1)
    bid_id: BidId
    kind: DeadlineKind
    due_at: datetime
    description: str | None = None
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> Deadline:
        if self.source.bid_id != self.bid_id:
            msg = "deadline source must belong to the deadline bid"
            raise ValueError(msg)
        if self.source.canonical_artifact_id is None:
            msg = "extracted deadlines must reference a canonical artifact"
            raise ValueError(msg)
        return self


class EntityKind(StrEnum):
    """Kinds of named entities relevant to bid management."""

    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"
    STANDARD = "STANDARD"
    CERTIFICATION = "CERTIFICATION"
    LOCATION = "LOCATION"
    CONTACT = "CONTACT"


class Entity(BidfusionModel):
    """A named entity extracted from the bid documents."""

    entity_id: str = Field(min_length=1)
    bid_id: BidId
    kind: EntityKind
    name: str = Field(min_length=1)
    normalized_name: str | None = None
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> Entity:
        if self.source.bid_id != self.bid_id:
            msg = "entity source must belong to the entity bid"
            raise ValueError(msg)
        if self.source.canonical_artifact_id is None:
            msg = "extracted entities must reference a canonical artifact"
            raise ValueError(msg)
        return self


class ExtractionStream(StrEnum):
    """Bounded extraction streams that feed the normalization fan-in."""

    REQUIREMENT = "REQUIREMENT"
    DEADLINE = "DEADLINE"
    ENTITY = "ENTITY"
    FORMALITY = "FORMALITY"
    SCOPE = "SCOPE"
    COMMERCIAL = "COMMERCIAL"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"


class FormalityKind(StrEnum):
    """Minimal categories for submission and document formalities."""

    SUBMISSION_INSTRUCTION = "SUBMISSION_INSTRUCTION"
    REQUIRED_FORMAT = "REQUIRED_FORMAT"
    REQUIRED_DOCUMENT = "REQUIRED_DOCUMENT"
    SIGNATURE_REQUIREMENT = "SIGNATURE_REQUIREMENT"
    PORTAL_REQUIREMENT = "PORTAL_REQUIREMENT"
    OTHER = "OTHER"


class Formality(BidfusionModel):
    """Source observation about a required submission formality."""

    formality_id: str = Field(min_length=1)
    bid_id: BidId
    kind: FormalityKind
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> Formality:
        _validate_canonical_source(self.bid_id, self.source, "formality")
        return self


class ScopeKind(StrEnum):
    """Minimal categories for requested bid scope."""

    SERVICE = "SERVICE"
    PRODUCT = "PRODUCT"
    DELIVERY = "DELIVERY"
    OTHER = "OTHER"


class Scope(BidfusionModel):
    """Source observation about requested service, product, or delivery scope."""

    scope_id: str = Field(min_length=1)
    bid_id: BidId
    kind: ScopeKind
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> Scope:
        _validate_canonical_source(self.bid_id, self.source, "scope")
        return self


class CommercialFindingKind(StrEnum):
    """Minimal categories for extracted commercial observations."""

    PRICING_MODEL = "PRICING_MODEL"
    BILLING_CONSTRAINT = "BILLING_CONSTRAINT"
    COMMERCIAL_TERM = "COMMERCIAL_TERM"
    SCORING_CRITERION = "SCORING_CRITERION"
    OTHER = "OTHER"


class CommercialFinding(BidfusionModel):
    """Source observation about a commercial constraint or criterion."""

    commercial_finding_id: str = Field(min_length=1)
    bid_id: BidId
    kind: CommercialFindingKind
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> CommercialFinding:
        _validate_canonical_source(self.bid_id, self.source, "commercial finding")
        return self


class SecurityFindingKind(StrEnum):
    """Minimal categories for bid-document security observations."""

    CONTROL = "CONTROL"
    STANDARD = "STANDARD"
    DATA_HANDLING = "DATA_HANDLING"
    ASSURANCE = "ASSURANCE"
    OTHER = "OTHER"


class ExtractedSecurityFinding(BidfusionModel):
    """Security observation from bid content, distinct from scanner findings."""

    security_finding_id: str = Field(min_length=1)
    bid_id: BidId
    kind: SecurityFindingKind
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    related_requirement_ids: tuple[RequirementId, ...] = Field(default_factory=tuple)
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> ExtractedSecurityFinding:
        _validate_canonical_source(self.bid_id, self.source, "security finding")
        return self


class ComplianceFindingKind(StrEnum):
    """Minimal categories for regulatory and compliance observations."""

    REGULATION = "REGULATION"
    STANDARD = "STANDARD"
    CERTIFICATION = "CERTIFICATION"
    POLICY = "POLICY"
    OTHER = "OTHER"


class ComplianceFinding(BidfusionModel):
    """Source observation that can later inform, but does not duplicate, the matrix."""

    compliance_finding_id: str = Field(min_length=1)
    bid_id: BidId
    kind: ComplianceFindingKind
    original_text: str = Field(min_length=1)
    normalized_text: str | None = Field(default=None, min_length=1)
    related_requirement_ids: tuple[RequirementId, ...] = Field(default_factory=tuple)
    source: SourceReference
    confidence: Confidence
    extraction: ExtractionInfo

    @model_validator(mode="after")
    def _source_is_canonical(self) -> ComplianceFinding:
        _validate_canonical_source(self.bid_id, self.source, "compliance finding")
        return self


def _validate_canonical_source(bid_id: BidId, source: SourceReference, kind: str) -> None:
    if source.bid_id != bid_id:
        msg = f"{kind} source must belong to the {kind} bid"
        raise ValueError(msg)
    if source.canonical_artifact_id is None:
        msg = f"extracted {kind} must reference a canonical artifact"
        raise ValueError(msg)


class ExtractionResultBase(BidfusionModel):
    """Shared metadata and lineage for one bounded extraction job."""

    artifact: ArtifactEnvelope
    bid_id: BidId
    agent_name: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    prompt_version: str | None = None
    model: str | None = Field(
        default=None,
        description="Model identifier assigned by the enterprise LLM Gateway",
    )
    document_ids: tuple[DocumentId, ...] = Field(default_factory=tuple)
    status: ProcessingStatus
    started_at: datetime
    finished_at: datetime
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _result_metadata_is_coherent(self) -> Self:
        if self.artifact.artifact_type is not ArtifactType.EXTRACTION_RESULT:
            msg = "extraction results require an extraction_result artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id:
            msg = "extraction artifact must belong to the result bid"
            raise ValueError(msg)
        if self.finished_at < self.started_at:
            msg = "finished_at cannot precede started_at"
            raise ValueError(msg)
        return self


def _validate_result_payload(
    result: ExtractionResultBase,
    item_bid_ids: list[BidId],
    sources: list[SourceReference],
) -> None:
    if any(bid_id != result.bid_id for bid_id in item_bid_ids):
        msg = "all extraction items must belong to the result bid"
        raise ValueError(msg)
    source_document_ids = {source.document_id for source in sources}
    if not source_document_ids.issubset(set(result.document_ids)):
        msg = "extraction payload sources must reference declared document IDs"
        raise ValueError(msg)
    input_artifacts = {item.artifact_id: item for item in result.artifact.input_artifacts}
    if any(
        source.canonical_artifact_id not in input_artifacts
        or input_artifacts[source.canonical_artifact_id].artifact_type
        is not ArtifactType.CANONICAL_DOCUMENT
        for source in sources
    ):
        msg = "extraction sources must be present in artifact input lineage"
        raise ValueError(msg)


class RequirementExtractionResult(ExtractionResultBase):
    """Bounded output of one requirement extraction job."""

    stream: Literal[ExtractionStream.REQUIREMENT] = ExtractionStream.REQUIREMENT
    requirements: tuple[Requirement, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> RequirementExtractionResult:
        _validate_result_payload(
            self,
            [requirement.bid_id for requirement in self.requirements],
            [
                source
                for requirement in self.requirements
                for source in (requirement.source, *requirement.additional_sources)
            ],
        )
        return self


class DeadlineExtractionResult(ExtractionResultBase):
    """Bounded output of one deadline extraction job."""

    stream: Literal[ExtractionStream.DEADLINE] = ExtractionStream.DEADLINE
    deadlines: tuple[Deadline, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> DeadlineExtractionResult:
        _validate_result_payload(
            self,
            [deadline.bid_id for deadline in self.deadlines],
            [deadline.source for deadline in self.deadlines],
        )
        return self


class EntityExtractionResult(ExtractionResultBase):
    """Bounded output of one entity extraction job."""

    stream: Literal[ExtractionStream.ENTITY] = ExtractionStream.ENTITY
    entities: tuple[Entity, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> EntityExtractionResult:
        _validate_result_payload(
            self,
            [entity.bid_id for entity in self.entities],
            [entity.source for entity in self.entities],
        )
        return self


class FormalityExtractionResult(ExtractionResultBase):
    """Bounded output of one formality extraction job."""

    stream: Literal[ExtractionStream.FORMALITY] = ExtractionStream.FORMALITY
    formalities: tuple[Formality, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> FormalityExtractionResult:
        _validate_result_payload(
            self,
            [formality.bid_id for formality in self.formalities],
            [formality.source for formality in self.formalities],
        )
        return self


class ScopeExtractionResult(ExtractionResultBase):
    """Bounded output of one scope extraction job."""

    stream: Literal[ExtractionStream.SCOPE] = ExtractionStream.SCOPE
    scope: tuple[Scope, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> ScopeExtractionResult:
        _validate_result_payload(
            self,
            [scope.bid_id for scope in self.scope],
            [scope.source for scope in self.scope],
        )
        return self


class CommercialExtractionResult(ExtractionResultBase):
    """Bounded output of one commercial extraction job."""

    stream: Literal[ExtractionStream.COMMERCIAL] = ExtractionStream.COMMERCIAL
    findings: tuple[CommercialFinding, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> CommercialExtractionResult:
        _validate_result_payload(
            self,
            [finding.bid_id for finding in self.findings],
            [finding.source for finding in self.findings],
        )
        return self


class SecurityExtractionResult(ExtractionResultBase):
    """Bounded output of one bid-content security extraction job."""

    stream: Literal[ExtractionStream.SECURITY] = ExtractionStream.SECURITY
    findings: tuple[ExtractedSecurityFinding, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> SecurityExtractionResult:
        _validate_result_payload(
            self,
            [finding.bid_id for finding in self.findings],
            [finding.source for finding in self.findings],
        )
        return self


class ComplianceExtractionResult(ExtractionResultBase):
    """Bounded output of one compliance extraction job."""

    stream: Literal[ExtractionStream.COMPLIANCE] = ExtractionStream.COMPLIANCE
    findings: tuple[ComplianceFinding, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _payload_is_isolated_and_lineaged(self) -> ComplianceExtractionResult:
        _validate_result_payload(
            self,
            [finding.bid_id for finding in self.findings],
            [finding.source for finding in self.findings],
        )
        return self


class ExtractionResult(ExtractionResultBase):
    """Foundation 1.1 compatibility envelope for the original three payloads.

    New extraction nodes use one of the focused result contracts above. This
    envelope remains only so existing Foundation 1.1 consumers can migrate
    without an unrelated breaking change.
    """

    requirements: tuple[Requirement, ...] = Field(default_factory=tuple)
    deadlines: tuple[Deadline, ...] = Field(default_factory=tuple)
    entities: tuple[Entity, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _result_is_isolated_and_lineaged(self) -> ExtractionResult:
        bid_ids = [
            *(requirement.bid_id for requirement in self.requirements),
            *(deadline.bid_id for deadline in self.deadlines),
            *(entity.bid_id for entity in self.entities),
        ]
        sources = [
            *(requirement.source for requirement in self.requirements),
            *(
                source
                for requirement in self.requirements
                for source in requirement.additional_sources
            ),
            *(deadline.source for deadline in self.deadlines),
            *(entity.source for entity in self.entities),
        ]
        _validate_result_payload(self, bid_ids, sources)
        return self
