"""Build the Bid Working Package from the normalized dataset (Domain J).

A working package can only exist for a run that passed the quality gate:
the public builder requires the gate report, accepts only status
``ACCEPTABLE``, and verifies that the report belongs to exactly this run,
bid, and normalized dataset. The unchecked assembly is a private internal
helper and is never exported.
"""

from __future__ import annotations

from datetime import datetime

from bidfusion.quality.gate import (
    QualityGateReport,
    QualityGateStatus,
    require_evaluated_artifacts,
)
from bidfusion.schemas.artifact import ArtifactType
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import (
    Deadline,
    DeadlineExtractionResult,
    Formality,
    FormalityExtractionResult,
    FormalityKind,
    Requirement,
    RequirementExtractionResult,
)
from bidfusion.schemas.ids import ArtifactId
from bidfusion.schemas.normalization import NormalizedBidDataset, NormalizedObjectReference
from bidfusion.schemas.working_package import (
    EvidencedStatement,
    OpenQuestion,
    RequirementsSummary,
    SubmissionInstructions,
    WorkingPackage,
)
from bidfusion.shared.payloads import seal_artifact

WORKING_PACKAGE_BUILDER_NAME = "bidfusion-working-package-builder"
WORKING_PACKAGE_BUILDER_VERSION = "0.1.0"
WORKING_PACKAGE_SCHEMA_VERSION = "1.0.0"
WORKING_PACKAGE_DOMAIN = "working_package"
WORKING_PACKAGE_CONTENT_REF = "working-package/working-package.payload.json"


def build_working_package(
    dataset: NormalizedBidDataset,
    *,
    requirements: RequirementExtractionResult,
    deadlines: DeadlineExtractionResult,
    formalities: FormalityExtractionResult,
    quality: QualityGateReport,
    artifact_id: ArtifactId,
    generated_at: datetime,
) -> WorkingPackage:
    """Assemble the human-facing working package with evidence links.

    The MVP builder requires all three extraction results and an
    ``ACCEPTABLE`` quality gate report bound to exactly this run, bid, and
    dataset: an incomplete or review-bound run can never silently look
    complete, and a report from another run can never release this one.
    """
    if quality.status is not QualityGateStatus.ACCEPTABLE:
        msg = (
            "a working package requires a quality gate report with status "
            f"ACCEPTABLE, got {quality.status.value}"
        )
        raise ValueError(msg)
    if quality.bid_id != dataset.bid_id:
        msg = "the quality gate report does not belong to this bid"
        raise ValueError(msg)
    if quality.run_id != dataset.artifact.run_id:
        msg = "the quality gate report does not belong to this run"
        raise ValueError(msg)
    require_evaluated_artifacts(
        quality,
        dataset=dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    return _build_working_package_unchecked(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        artifact_id=artifact_id,
        generated_at=generated_at,
    )


def _build_working_package_unchecked(
    dataset: NormalizedBidDataset,
    *,
    requirements: RequirementExtractionResult,
    deadlines: DeadlineExtractionResult,
    formalities: FormalityExtractionResult,
    artifact_id: ArtifactId,
    generated_at: datetime,
) -> WorkingPackage:
    """UNSAFE internal assembly without quality gate enforcement.

    Module-private on purpose: it performs no gate or binding checks and
    must only ever be reached through :func:`build_working_package`.
    """
    requirements_by_id = {item.requirement_id: item for item in requirements.requirements}
    deadlines_by_id = {item.deadline_id: item for item in deadlines.deadlines}
    formalities_by_id = {item.formality_id: item for item in formalities.formalities}

    normalized_requirements = [
        (reference, _item(requirements_by_id, reference)) for reference in dataset.requirements
    ]
    timeline = tuple(
        sorted(
            (_item(deadlines_by_id, reference) for reference in dataset.deadlines),
            key=lambda deadline: (deadline.due_at, deadline.deadline_id),
        )
    )

    modality_counts: dict[RequirementModality, int] = {}
    category_counts: dict[RequirementCategory, int] = {}
    for _, requirement in normalized_requirements:
        modality_counts[requirement.modality] = modality_counts.get(requirement.modality, 0) + 1
        category_counts[requirement.category] = category_counts.get(requirement.category, 0) + 1

    open_questions = tuple(
        OpenQuestion(
            question_id=f"OQ-{sequence:03d}",
            statement=_statement(requirement.original_text, reference),
            reason="the requirement text expresses no clear modality",
            potential_clarification=True,
        )
        for sequence, (reference, requirement) in enumerate(
            (
                (reference, requirement)
                for reference, requirement in normalized_requirements
                if requirement.modality is RequirementModality.UNKNOWN
            ),
            start=1,
        )
    )

    submission_instructions = _submission_instructions(dataset, formalities_by_id)
    requirements_summary = RequirementsSummary(
        total=len(normalized_requirements),
        by_modality=modality_counts,
        by_category=category_counts,
    )
    critical_requirements = tuple(
        requirement.requirement_id
        for _, requirement in normalized_requirements
        if requirement.modality is RequirementModality.MUST
    )
    return seal_artifact(
        lambda envelope: WorkingPackage(
            artifact=envelope,
            source_dataset=dataset.artifact.as_reference(),
            bid_id=dataset.bid_id,
            generated_at=generated_at,
            timeline=timeline,
            submission_instructions=submission_instructions,
            requirements_summary=requirements_summary,
            critical_requirements=critical_requirements,
            open_questions=open_questions,
        ),
        artifact_id=artifact_id,
        bid_id=dataset.bid_id,
        run_id=dataset.artifact.run_id,
        artifact_type=ArtifactType.WORKING_PACKAGE,
        schema_version=WORKING_PACKAGE_SCHEMA_VERSION,
        domain=WORKING_PACKAGE_DOMAIN,
        content_ref=WORKING_PACKAGE_CONTENT_REF,
        producer_component=WORKING_PACKAGE_BUILDER_NAME,
        producer_version=WORKING_PACKAGE_BUILDER_VERSION,
        input_artifacts=(dataset.artifact.as_reference(),),
        created_at=generated_at,
    )


def _submission_instructions(
    dataset: NormalizedBidDataset,
    formalities_by_id: dict[str, Formality],
) -> SubmissionInstructions:
    portal: EvidencedStatement | None = None
    upload_process: list[EvidencedStatement] = []
    formats: list[EvidencedStatement] = []
    signatures_required: list[EvidencedStatement] = []
    special_requirements: list[EvidencedStatement] = []

    for reference in dataset.formalities:
        formality = _item(formalities_by_id, reference)
        statement = _statement(
            formality.normalized_text or formality.original_text,
            reference,
        )
        if formality.kind is FormalityKind.PORTAL_REQUIREMENT and portal is None:
            portal = statement
        elif formality.kind is FormalityKind.SUBMISSION_INSTRUCTION:
            upload_process.append(statement)
        elif formality.kind is FormalityKind.REQUIRED_FORMAT:
            formats.append(statement)
        elif formality.kind is FormalityKind.SIGNATURE_REQUIREMENT:
            signatures_required.append(statement)
        else:
            special_requirements.append(statement)

    return SubmissionInstructions(
        portal=portal,
        upload_process=tuple(upload_process),
        formats=tuple(formats),
        signatures_required=tuple(signatures_required),
        special_requirements=tuple(special_requirements),
    )


def _statement(text: str, reference: NormalizedObjectReference) -> EvidencedStatement:
    return EvidencedStatement(
        text=text,
        normalized_object_ids=(reference.object_id,),
        sources=reference.sources,
    )


def _item[ItemT: (Requirement, Deadline, Formality)](
    items_by_id: dict[str, ItemT],
    reference: NormalizedObjectReference,
) -> ItemT:
    item = items_by_id.get(reference.object_id)
    if item is None:
        msg = f"normalized reference {reference.object_id} has no backing extraction item"
        raise ValueError(msg)
    return item
