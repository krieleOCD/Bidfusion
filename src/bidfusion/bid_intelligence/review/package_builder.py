"""Deterministic builder of the Reviewed Working Package snapshot.

Pure assembly: the builder binds the run's authoritative requirement
extraction result, the deterministic assessments computed from it, and
the reviews recorded for this run into one sealed
:class:`ReviewedWorkingPackage`. It mutates nothing — not the
requirements, not the assessments, not the review store, and no golden
state — and given the same authoritative inputs it produces the same
package content; only ``created_at`` (and the identifiers derived from
the caller-supplied artifact id) are explicitly versioned creation
metadata.

Fail-closed binding rules:

- every assessment must correspond to exactly one extracted requirement
  of this run, with matching bid, text, and modality;
- every extracted requirement must have exactly one assessment;
- a review recorded for another bid or run is rejected outright;
- a stale review — one whose assessment digest no longer matches the
  current assessment — is *excluded* (it remains history, never applied),
  via the same projection rule the review pages use.
"""

from __future__ import annotations

from datetime import datetime

from bidfusion.bid_intelligence.matching.contracts import (
    ASSESSMENT_VERSION,
    RequirementKnowledgeAssessment,
)
from bidfusion.bid_intelligence.review.contracts import (
    RequirementAssessmentReview,
    assessment_digest,
)
from bidfusion.bid_intelligence.review.package import (
    REVIEWED_PACKAGE_DOMAIN,
    REVIEWED_PACKAGE_SCHEMA_VERSION,
    PackageGoldenKnowledge,
    PackageHumanReview,
    PackageMachineAssessment,
    PackageReviewState,
    PackageRfpRequirement,
    ReviewedPackageRequirement,
    ReviewedWorkingPackage,
    package_id_for,
    summarize_entries,
)
from bidfusion.bid_intelligence.review.service import project_reviewed_assessments
from bidfusion.schemas.artifact import ArtifactType
from bidfusion.schemas.extraction import Requirement, RequirementExtractionResult
from bidfusion.schemas.ids import ArtifactId
from bidfusion.shared.payloads import seal_artifact

REVIEWED_PACKAGE_BUILDER_NAME = "bidfusion-reviewed-working-package-builder"
REVIEWED_PACKAGE_BUILDER_VERSION = "0.1.0"


class PackageBuildError(ValueError):
    """The package inputs do not bind; the message is static and safe."""


_UNBOUND_ASSESSMENT = "an assessment does not correspond to a requirement of this run"
_MISSING_ASSESSMENT = "a requirement of this run has no assessment"
_DUPLICATE_ASSESSMENT = "a requirement of this run has more than one assessment"
_FOREIGN_REVIEW = "a review does not belong to this bid and run"
_MIXED_ASSESSMENT_VERSIONS = "all assessments of one package must share one version"


def content_ref_for(package_version: int) -> str:
    """The controlled payload filename for one package version."""
    return f"reviewed-working-package-v{package_version:04d}.payload.json"


def build_reviewed_working_package(
    requirements: RequirementExtractionResult,
    *,
    assessments: tuple[RequirementKnowledgeAssessment, ...],
    reviews: tuple[RequirementAssessmentReview, ...],
    package_version: int,
    artifact_id: ArtifactId,
    created_at: datetime,
) -> ReviewedWorkingPackage:
    """Assemble one sealed Reviewed Working Package snapshot.

    Entries follow the authoritative requirement extraction order.
    Raises :class:`PackageBuildError` when the inputs do not bind
    exactly; no partial package is ever produced.
    """
    bid_id = requirements.bid_id
    run_id = requirements.artifact.run_id

    known_requirements = {item.requirement_id for item in requirements.requirements}
    assessments_by_requirement: dict[str, RequirementKnowledgeAssessment] = {}
    for assessment in assessments:
        if assessment.requirement_id in assessments_by_requirement:
            raise PackageBuildError(_DUPLICATE_ASSESSMENT)
        if assessment.requirement_id not in known_requirements or assessment.bid_id != bid_id:
            raise PackageBuildError(_UNBOUND_ASSESSMENT)
        assessments_by_requirement[assessment.requirement_id] = assessment

    for review in reviews:
        if review.bid_id != bid_id or review.run_id != run_id:
            raise PackageBuildError(_FOREIGN_REVIEW)

    ordered_assessments: list[RequirementKnowledgeAssessment] = []
    for requirement in requirements.requirements:
        bound = assessments_by_requirement.get(requirement.requirement_id)
        if bound is None:
            raise PackageBuildError(_MISSING_ASSESSMENT)
        expected_text = requirement.normalized_text or requirement.original_text
        if (
            bound.requirement_text != expected_text
            or bound.requirement_modality is not requirement.modality
            or bound.requirement_source != requirement.source
        ):
            raise PackageBuildError(_UNBOUND_ASSESSMENT)
        ordered_assessments.append(bound)

    versions = {assessment.assessment_version for assessment in ordered_assessments}
    if len(versions) > 1:
        raise PackageBuildError(_MIXED_ASSESSMENT_VERSIONS)
    assessment_version = next(iter(versions), ASSESSMENT_VERSION)

    projection = project_reviewed_assessments(tuple(ordered_assessments), reviews)
    entries = tuple(
        _entry(requirement, reviewed.assessment, reviewed.review)
        for requirement, reviewed in zip(
            requirements.requirements, projection.reviewed, strict=True
        )
    )
    summary = summarize_entries(entries)
    state = (
        PackageReviewState.REVIEW_COMPLETE
        if summary.pending == 0
        else PackageReviewState.REVIEW_INCOMPLETE
    )
    return seal_artifact(
        lambda envelope: ReviewedWorkingPackage(
            artifact=envelope,
            package_id=package_id_for(run_id, package_version),
            package_version=package_version,
            bid_id=bid_id,
            run_id=run_id,
            created_at=created_at,
            assessment_version=assessment_version,
            source_requirements=requirements.artifact.as_reference(),
            requirements=entries,
            summary=summary,
            package_review_state=state,
        ),
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.REVIEWED_WORKING_PACKAGE,
        schema_version=REVIEWED_PACKAGE_SCHEMA_VERSION,
        domain=REVIEWED_PACKAGE_DOMAIN,
        content_ref=content_ref_for(package_version),
        producer_component=REVIEWED_PACKAGE_BUILDER_NAME,
        producer_version=REVIEWED_PACKAGE_BUILDER_VERSION,
        input_artifacts=(requirements.artifact.as_reference(),),
        created_at=created_at,
    )


def _entry(
    requirement: Requirement,
    assessment: RequirementKnowledgeAssessment,
    review: RequirementAssessmentReview | None,
) -> ReviewedPackageRequirement:
    return ReviewedPackageRequirement(
        rfp=PackageRfpRequirement(
            requirement_id=requirement.requirement_id,
            text=requirement.original_text,
            modality=requirement.modality,
            source=requirement.source,
            additional_sources=requirement.additional_sources,
        ),
        machine=PackageMachineAssessment(
            assessment_id=assessment.assessment_id,
            assessment_version=assessment.assessment_version,
            assessment_digest=assessment_digest(assessment),
            requirement_language=assessment.requirement_language,
            technology_hint=assessment.technology_hint,
            capability_hints=assessment.capability_hints,
            match_status=assessment.match_status,
            matched_claim_id=assessment.matched_claim_id,
            matched_capability=assessment.matched_capability,
            rationale=assessment.rationale,
        ),
        golden=PackageGoldenKnowledge(
            claim_status=assessment.knowledge_claim_status,
            evidence_refs=assessment.evidence_refs,
        ),
        human_review=None
        if review is None
        else PackageHumanReview(
            review_id=review.review_id,
            review_version=review.review_version,
            decision=review.decision,
            reviewer=review.reviewer,
            reviewed_at=review.reviewed_at,
            rationale=review.rationale,
        ),
    )
