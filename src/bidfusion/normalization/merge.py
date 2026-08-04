"""Deterministic fan-in of the MVP extraction streams (Domain G).

Exact duplicates (same normalized text, or same kind and due time for
deadlines) collapse into one normalized object that keeps every source —
but only when every duplicate agrees on its business attributes. Duplicates
with conflicting modality, category, kind, or description are **not**
silently merged: each stays a separate normalized object and the
disagreement is preserved as an ``UnresolvedConflict`` for QA or human
review. Failed extraction streams are recorded in
``ExtractionCompleteness`` instead of being hidden.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactType
from bidfusion.schemas.extraction import (
    DeadlineExtractionResult,
    ExtractionStream,
    FormalityExtractionResult,
    RequirementExtractionResult,
)
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.normalization import (
    ExtractionCompleteness,
    NormalizedBidDataset,
    NormalizedObjectReference,
    NormalizedObjectType,
    UnresolvedConflict,
)
from bidfusion.schemas.provenance import SourceReference
from bidfusion.shared.payloads import seal_artifact

NORMALIZATION_COMPONENT_NAME = "bidfusion-normalization-merge"
NORMALIZATION_COMPONENT_VERSION = "0.1.0"
NORMALIZED_SCHEMA_VERSION = "1.0.0"
NORMALIZED_DOMAIN = "normalized_bid_dataset"
NORMALIZED_CONTENT_REF = "normalized/normalized-bid-dataset.payload.json"

MVP_EXPECTED_STREAMS = (
    ExtractionStream.REQUIREMENT,
    ExtractionStream.DEADLINE,
    ExtractionStream.FORMALITY,
)


@dataclass(frozen=True, slots=True)
class _MergeItem:
    """One extracted item prepared for duplicate grouping."""

    object_id: str
    key: str
    attributes: tuple[str, ...]
    sources: tuple[SourceReference, ...]


@dataclass(frozen=True, slots=True)
class _ConflictSpec:
    """A preserved disagreement between duplicates, before ID assignment."""

    object_ids: tuple[str, ...]
    description: str
    sources: tuple[SourceReference, ...]


def merge_extractions(
    *,
    bid_id: BidId,
    run_id: RunId,
    artifact_id: ArtifactId,
    created_at: datetime,
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
    failed_streams: tuple[ExtractionStream, ...] = (),
) -> NormalizedBidDataset:
    """Merge the MVP extraction results into one normalized dataset."""
    present: dict[ExtractionStream, ArtifactEnvelope] = {}
    if requirements is not None:
        present[ExtractionStream.REQUIREMENT] = requirements.artifact
    if deadlines is not None:
        present[ExtractionStream.DEADLINE] = deadlines.artifact
    if formalities is not None:
        present[ExtractionStream.FORMALITY] = formalities.artifact
    if set(present) & set(failed_streams):
        msg = "a stream cannot be both completed and failed"
        raise ValueError(msg)

    conflict_specs: list[_ConflictSpec] = []
    requirement_references = _merged_references(
        bid_id=bid_id,
        envelope=present.get(ExtractionStream.REQUIREMENT),
        object_type=NormalizedObjectType.REQUIREMENT,
        attribute_label="modality/category",
        items=(
            _MergeItem(
                object_id=item.requirement_id,
                key=(item.normalized_text or item.original_text).strip().lower(),
                attributes=(item.modality.value, item.category.value),
                sources=(item.source, *item.additional_sources),
            )
            for item in (requirements.requirements if requirements is not None else ())
        ),
        conflict_specs=conflict_specs,
    )
    deadline_references = _merged_references(
        bid_id=bid_id,
        envelope=present.get(ExtractionStream.DEADLINE),
        object_type=NormalizedObjectType.DEADLINE,
        attribute_label="description",
        items=(
            _MergeItem(
                object_id=item.deadline_id,
                key=f"{item.kind.value}@{item.due_at.isoformat()}",
                attributes=(item.description or "",),
                sources=(item.source,),
            )
            for item in (deadlines.deadlines if deadlines is not None else ())
        ),
        conflict_specs=conflict_specs,
    )
    formality_references = _merged_references(
        bid_id=bid_id,
        envelope=present.get(ExtractionStream.FORMALITY),
        object_type=NormalizedObjectType.FORMALITY,
        attribute_label="kind",
        items=(
            _MergeItem(
                object_id=item.formality_id,
                key=(item.normalized_text or item.original_text).strip().lower(),
                attributes=(item.kind.value,),
                sources=(item.source,),
            )
            for item in (formalities.formalities if formalities is not None else ())
        ),
        conflict_specs=conflict_specs,
    )

    unresolved_conflicts = tuple(
        UnresolvedConflict(
            bid_id=bid_id,
            conflict_id=f"CONF-{sequence:03d}",
            object_ids=spec.object_ids,
            description=spec.description,
            sources=spec.sources,
        )
        for sequence, spec in enumerate(conflict_specs, start=1)
    )
    completeness = ExtractionCompleteness(
        expected_streams=MVP_EXPECTED_STREAMS,
        completed_streams=tuple(stream for stream in MVP_EXPECTED_STREAMS if stream in present),
        failed_streams=failed_streams,
    )
    return seal_artifact(
        lambda envelope: NormalizedBidDataset(
            artifact=envelope,
            bid_id=bid_id,
            completeness=completeness,
            requirements=requirement_references,
            deadlines=deadline_references,
            formalities=formality_references,
            unresolved_conflicts=unresolved_conflicts,
        ),
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.NORMALIZED_BID_DATASET,
        schema_version=NORMALIZED_SCHEMA_VERSION,
        domain=NORMALIZED_DOMAIN,
        content_ref=NORMALIZED_CONTENT_REF,
        producer_component=NORMALIZATION_COMPONENT_NAME,
        producer_version=NORMALIZATION_COMPONENT_VERSION,
        input_artifacts=tuple(
            present[stream].as_reference() for stream in MVP_EXPECTED_STREAMS if stream in present
        ),
        created_at=created_at,
    )


def _merged_references(
    *,
    bid_id: BidId,
    envelope: ArtifactEnvelope | None,
    object_type: NormalizedObjectType,
    attribute_label: str,
    items: Iterable[_MergeItem],
    conflict_specs: list[_ConflictSpec],
) -> tuple[NormalizedObjectReference, ...]:
    """Collapse agreeing duplicates; keep disagreeing duplicates and record them."""
    grouped: dict[str, list[_MergeItem]] = {}
    for item in items:
        grouped.setdefault(item.key, []).append(item)
    if grouped and envelope is None:  # pragma: no cover - guarded by merge_extractions
        msg = "normalized objects require their extraction envelope"
        raise ValueError(msg)

    references: list[NormalizedObjectReference] = []
    for members in grouped.values():
        assert envelope is not None
        attribute_variants = {member.attributes for member in members}
        if len(attribute_variants) <= 1:
            first = members[0]
            references.append(
                NormalizedObjectReference(
                    bid_id=bid_id,
                    object_id=first.object_id,
                    object_type=object_type,
                    source_artifacts=(envelope.as_reference(),),
                    sources=tuple(source for member in members for source in member.sources),
                )
            )
            continue
        references.extend(
            NormalizedObjectReference(
                bid_id=bid_id,
                object_id=member.object_id,
                object_type=object_type,
                source_artifacts=(envelope.as_reference(),),
                sources=member.sources,
            )
            for member in members
        )
        variants = " vs ".join("/".join(member.attributes) for member in members)
        conflict_specs.append(
            _ConflictSpec(
                object_ids=tuple(member.object_id for member in members),
                description=(
                    f"duplicate {object_type.value.lower()} with conflicting "
                    f"{attribute_label}: {variants}"
                ),
                sources=tuple(source for member in members for source in member.sources),
            )
        )
    return tuple(references)
