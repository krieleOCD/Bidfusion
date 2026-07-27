"""Explicit fan-in contract between atomic extraction and QA."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, computed_field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import BidfusionModel, Severity
from bidfusion.schemas.extraction import ExtractionStream
from bidfusion.schemas.ids import BidId
from bidfusion.schemas.provenance import SourceReference


class NormalizedObjectType(StrEnum):
    """Business object kinds referenced by the first normalized dataset."""

    REQUIREMENT = "REQUIREMENT"
    DEADLINE = "DEADLINE"
    ENTITY = "ENTITY"
    FORMALITY = "FORMALITY"
    SCOPE = "SCOPE"
    COMMERCIAL_FINDING = "COMMERCIAL_FINDING"
    SECURITY_FINDING = "SECURITY_FINDING"
    COMPLIANCE_FINDING = "COMPLIANCE_FINDING"


class NormalizedObjectReference(BidfusionModel):
    """Reference to one normalized object and the extraction artifacts behind it."""

    bid_id: BidId
    object_id: str = Field(min_length=1)
    object_type: NormalizedObjectType
    source_artifacts: tuple[ArtifactReference, ...] = Field(min_length=1)
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _source_artifacts_are_isolated(self) -> NormalizedObjectReference:
        if any(artifact.bid_id != self.bid_id for artifact in self.source_artifacts):
            msg = "normalized object source artifacts must belong to the same bid"
            raise ValueError(msg)
        if any(source.bid_id != self.bid_id for source in self.sources):
            msg = "normalized object provenance must belong to the same bid"
            raise ValueError(msg)
        return self


class NormalizedRelationship(BidfusionModel):
    """Typed relationship between normalized business objects."""

    bid_id: BidId
    from_object_id: str = Field(min_length=1)
    to_object_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sources_are_bid_isolated(self) -> NormalizedRelationship:
        if any(source.bid_id != self.bid_id for source in self.sources):
            msg = "relationship sources must belong to the relationship bid"
            raise ValueError(msg)
        return self


class UnresolvedConflict(BidfusionModel):
    """Conflict preserved for QA or human review instead of silently resolved."""

    bid_id: BidId
    conflict_id: str = Field(min_length=1)
    object_ids: tuple[str, ...] = Field(min_length=2)
    description: str = Field(min_length=1)
    severity: Severity = Severity.MEDIUM
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sources_are_bid_isolated(self) -> UnresolvedConflict:
        if any(source.bid_id != self.bid_id for source in self.sources):
            msg = "conflict sources must belong to the conflict bid"
            raise ValueError(msg)
        return self


class ExtractionCompletenessState(StrEnum):
    """Overall state derived from the expected extraction streams."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ExtractionCompleteness(BidfusionModel):
    """Explicit execution accounting at the normalization fan-in boundary."""

    expected_streams: tuple[ExtractionStream, ...] = Field(min_length=1)
    completed_streams: tuple[ExtractionStream, ...] = ()
    failed_streams: tuple[ExtractionStream, ...] = ()
    skipped_streams: tuple[ExtractionStream, ...] = ()

    @model_validator(mode="after")
    def _streams_are_unique_expected_and_disjoint(self) -> ExtractionCompleteness:
        groups = (
            self.expected_streams,
            self.completed_streams,
            self.failed_streams,
            self.skipped_streams,
        )
        if any(len(group) != len(set(group)) for group in groups):
            msg = "extraction completeness cannot contain duplicate streams"
            raise ValueError(msg)
        expected = set(self.expected_streams)
        observed = {
            *self.completed_streams,
            *self.failed_streams,
            *self.skipped_streams,
        }
        if not observed.issubset(expected):
            msg = "extraction completeness cannot report an unexpected stream"
            raise ValueError(msg)
        if (
            set(self.completed_streams) & set(self.failed_streams)
            or set(self.completed_streams) & set(self.skipped_streams)
            or set(self.failed_streams) & set(self.skipped_streams)
        ):
            msg = "an extraction stream can have only one completion outcome"
            raise ValueError(msg)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state(self) -> ExtractionCompletenessState:
        """Derive whether fan-in is complete, partial, or failed."""
        if self.failed_streams:
            return ExtractionCompletenessState.FAILED
        if set(self.completed_streams) == set(self.expected_streams):
            return ExtractionCompletenessState.COMPLETE
        return ExtractionCompletenessState.PARTIAL


class NormalizedBidDataset(BidfusionModel):
    """Typed, lineaged fan-in aggregate consumed by QA and Working Package."""

    artifact: ArtifactEnvelope
    bid_id: BidId
    completeness: ExtractionCompleteness
    requirements: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    deadlines: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    entities: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    formalities: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    scope: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    commercial_findings: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    security_findings: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    compliance_findings: tuple[NormalizedObjectReference, ...] = Field(default_factory=tuple)
    relationships: tuple[NormalizedRelationship, ...] = Field(default_factory=tuple)
    unresolved_conflicts: tuple[UnresolvedConflict, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _fan_in_is_typed_and_isolated(self) -> NormalizedBidDataset:
        if self.artifact.artifact_type is not ArtifactType.NORMALIZED_BID_DATASET:
            msg = "normalized datasets require a normalized_bid_dataset artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id:
            msg = "normalized dataset artifact must belong to the dataset bid"
            raise ValueError(msg)
        collections = (
            (NormalizedObjectType.REQUIREMENT, self.requirements),
            (NormalizedObjectType.DEADLINE, self.deadlines),
            (NormalizedObjectType.ENTITY, self.entities),
            (NormalizedObjectType.FORMALITY, self.formalities),
            (NormalizedObjectType.SCOPE, self.scope),
            (NormalizedObjectType.COMMERCIAL_FINDING, self.commercial_findings),
            (NormalizedObjectType.SECURITY_FINDING, self.security_findings),
            (NormalizedObjectType.COMPLIANCE_FINDING, self.compliance_findings),
        )
        input_ids = {artifact.artifact_id for artifact in self.artifact.input_artifacts}
        object_ids: set[str] = set()
        for expected_type, references in collections:
            for reference in references:
                if reference.bid_id != self.bid_id:
                    msg = "normalized object references must belong to the dataset bid"
                    raise ValueError(msg)
                if reference.object_type is not expected_type:
                    msg = f"{expected_type.value} collection contains another object type"
                    raise ValueError(msg)
                if any(
                    artifact.artifact_id not in input_ids for artifact in reference.source_artifacts
                ):
                    msg = "normalized object sources must be present in dataset input lineage"
                    raise ValueError(msg)
                if any(
                    artifact.artifact_type is not ArtifactType.EXTRACTION_RESULT
                    for artifact in reference.source_artifacts
                ):
                    msg = "normalized object sources must be extraction_result artifacts"
                    raise ValueError(msg)
                if reference.object_id in object_ids:
                    msg = "normalized object IDs must be unique within a dataset"
                    raise ValueError(msg)
                object_ids.add(reference.object_id)
        for relationship in self.relationships:
            if relationship.bid_id != self.bid_id:
                msg = "normalized relationships must belong to the dataset bid"
                raise ValueError(msg)
            if (
                relationship.from_object_id not in object_ids
                or relationship.to_object_id not in object_ids
            ):
                msg = "normalized relationships must reference dataset objects"
                raise ValueError(msg)
        for conflict in self.unresolved_conflicts:
            if conflict.bid_id != self.bid_id:
                msg = "unresolved conflicts must belong to the dataset bid"
                raise ValueError(msg)
            if any(object_id not in object_ids for object_id in conflict.object_ids):
                msg = "unresolved conflicts must reference dataset objects"
                raise ValueError(msg)
        return self
