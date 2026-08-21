"""Deterministic Reviewed Working Package builder: binding and versioning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import synthetic_golden_claims

from bidfusion.bid_intelligence.matching import (
    ClaimsSnapshot,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    assess_requirements,
)
from bidfusion.bid_intelligence.review import (
    PackageBuildError,
    PackageReviewState,
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewState,
    build_reviewed_working_package,
    content_ref_for,
    package_id_for,
    record_requirement_assessment_review,
)
from bidfusion.golden_dataset.contracts import ClaimStatus, MatchStatus
from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import ProcessingStatus, RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement, RequirementExtractionResult
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference
from bidfusion.shared.payloads import seal_artifact, verify_sealed_artifact

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260821-0001"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
CANONICAL_ID = "ART-20260821-000011"

_CANONICAL_REF = ArtifactReference(
    artifact_id=CANONICAL_ID,
    bid_id=BID_ID,
    run_id=RUN_ID,
    artifact_type=ArtifactType.CANONICAL_DOCUMENT,
    schema_version="1.0.0",
    content_ref="canonical/DOC-001.payload.json",
    content_hash="c" * 64,
)

_TEXTS = (
    (
        "The service MUST provide 24/7 monitoring using Microsoft Sentinel.",
        RequirementModality.MUST,
    ),
    (
        "The provider MUST support Microsoft Defender XDR investigations.",
        RequirementModality.MUST,
    ),
    ("The provider SHOULD describe its catering arrangements.", RequirementModality.SHOULD),
    ("Vectra network detection MUST be part of the service.", RequirementModality.MUST),
)


def _requirement(sequence: int, text: str, modality: RequirementModality) -> Requirement:
    return Requirement(
        requirement_id=f"REQ-{sequence:06d}",
        bid_id=BID_ID,
        original_text=text,
        modality=modality,
        category=RequirementCategory.TECHNICAL,
        confidence=0.9,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-001",
            filename="mtd-requirements.docx",
            document_hash="a" * 64,
            locator=SourceLocator(paragraph_id=f"p-{sequence}"),
            canonical_artifact_id=CANONICAL_ID,
        ),
        extraction=ExtractionInfo(method="rule", producer="test", producer_version="0.1.0"),
    )


def _extraction_result(
    texts: tuple[tuple[str, RequirementModality], ...] = _TEXTS,
) -> RequirementExtractionResult:
    items = tuple(
        _requirement(sequence, text, modality)
        for sequence, (text, modality) in enumerate(texts, start=1)
    )
    return seal_artifact(
        lambda envelope: RequirementExtractionResult(
            artifact=envelope,
            bid_id=BID_ID,
            agent_name="test-extractor",
            agent_version="0.1.0",
            document_ids=("DOC-001",),
            status=ProcessingStatus.COMPLETED,
            started_at=NOW,
            finished_at=NOW,
            requirements=items,
        ),
        artifact_id="ART-20260821-000001",
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version="1.0.0",
        domain="extraction/requirement",
        content_ref="extraction/requirement-extraction.payload.json",
        producer_component="test-extractor",
        producer_version="0.1.0",
        input_artifacts=(_CANONICAL_REF,),
        created_at=NOW,
    )


def _assessed(
    requirements: RequirementExtractionResult,
) -> tuple[RequirementKnowledgeAssessment, ...]:
    snapshot = ClaimsSnapshot(state=KnowledgeStoreState.AVAILABLE, claims=synthetic_golden_claims())
    return assess_requirements(requirements.requirements, snapshot).assessments


def _review(
    assessment: RequirementKnowledgeAssessment,
    decision: ReviewDecision = ReviewDecision.CONFIRMED,
    existing: tuple[RequirementAssessmentReview, ...] = (),
) -> RequirementAssessmentReview:
    return record_requirement_assessment_review(
        assessment,
        decision=decision,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id=RUN_ID,
        existing=existing,
    )


def test_all_pending_builds_an_incomplete_package() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)

    package = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=(),
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert package.package_review_state is PackageReviewState.REVIEW_INCOMPLETE
    assert package.summary.total_requirements == len(_TEXTS)
    assert package.summary.pending == len(_TEXTS)
    assert package.summary.reviewed == 0
    assert all(entry.human_review is None for entry in package.requirements)
    verify_sealed_artifact(package, domain="reviewed_working_package")


def test_mixed_review_states_are_carried_without_flattening() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    reviews = (
        _review(assessments[0], ReviewDecision.CONFIRMED),
        _review(assessments[1], ReviewDecision.REJECTED),
        _review(assessments[2], ReviewDecision.NEEDS_CLARIFICATION),
    )

    package = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert package.package_review_state is PackageReviewState.REVIEW_INCOMPLETE
    assert package.summary.confirmed_candidate == 1
    assert package.summary.rejected_candidate == 1
    assert package.summary.needs_clarification == 1
    assert package.summary.pending == len(_TEXTS) - 3

    confirmed, rejected, clarify, pending = package.requirements
    # Machine candidate and human decision stay independent dimensions:
    # a rejected candidate keeps its MATCHED machine status, and the golden
    # claim status stays EXTRACTED_UNVERIFIED regardless of any decision.
    assert confirmed.machine.match_status is MatchStatus.MATCHED
    assert confirmed.review_state is ReviewState.CONFIRMED
    assert rejected.machine.match_status is MatchStatus.MATCHED
    assert rejected.review_state is ReviewState.REJECTED
    assert rejected.golden.claim_status is ClaimStatus.EXTRACTED_UNVERIFIED
    assert clarify.review_state is ReviewState.NEEDS_CLARIFICATION
    assert pending.review_state is ReviewState.PENDING


def test_all_reviewed_builds_a_complete_package() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    reviews = tuple(_review(assessment) for assessment in assessments)

    package = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert package.package_review_state is PackageReviewState.REVIEW_COMPLETE
    assert package.summary.pending == 0
    assert package.summary.reviewed == len(_TEXTS)


def test_a_stale_review_is_excluded_and_the_entry_stays_pending() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    changed = assessments[0].model_copy(update={"rationale": "different content"})
    stale = _review(changed)

    package = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=(stale,),
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert package.requirements[0].human_review is None
    assert package.summary.pending == len(_TEXTS)


def test_a_foreign_review_fails_the_build_closed() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    foreign = _review(assessments[0]).model_copy(update={"run_id": "RUN-99999999-9999"})

    with pytest.raises(PackageBuildError):
        build_reviewed_working_package(
            requirements,
            assessments=assessments,
            reviews=(foreign,),
            package_version=1,
            artifact_id="ART-20260821-000099",
            created_at=NOW,
        )


def test_missing_extra_or_duplicate_assessments_fail_closed() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    stranger = _assessed(_extraction_result((_TEXTS[0],)))[0].model_copy(
        update={"requirement_id": "REQ-000099"}
    )

    for bad in (
        assessments[:-1],
        (*assessments, stranger),
        (*assessments, assessments[0]),
    ):
        with pytest.raises(PackageBuildError):
            build_reviewed_working_package(
                requirements,
                assessments=bad,
                reviews=(),
                package_version=1,
                artifact_id="ART-20260821-000099",
                created_at=NOW,
            )


def test_an_assessment_whose_text_disagrees_fails_closed() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    drifted = (
        assessments[0].model_copy(update={"requirement_text": "different wording"}),
        *assessments[1:],
    )

    with pytest.raises(PackageBuildError):
        build_reviewed_working_package(
            requirements,
            assessments=drifted,
            reviews=(),
            package_version=1,
            artifact_id="ART-20260821-000099",
            created_at=NOW,
        )


def test_entries_follow_the_authoritative_requirement_order() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    shuffled = tuple(reversed(assessments))

    package = build_reviewed_working_package(
        requirements,
        assessments=shuffled,
        reviews=(),
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert [entry.rfp.requirement_id for entry in package.requirements] == [
        item.requirement_id for item in requirements.requirements
    ]


def test_the_same_inputs_produce_the_same_sealed_package() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    reviews = (_review(assessments[0]),)

    first = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )
    second = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert first == second
    assert first.artifact.content_hash == second.artifact.content_hash


def test_versions_differ_only_where_review_state_differs() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    first = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=(_review(assessments[0]),),
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )
    more_reviews = (
        _review(assessments[0]),
        _review(assessments[1], ReviewDecision.REJECTED),
    )
    second = build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=more_reviews,
        package_version=2,
        artifact_id="ART-20260821-000100",
        created_at=NOW,
    )

    assert first.package_version == 1
    assert second.package_version == 2
    assert first.package_id != second.package_id
    assert second.package_id == package_id_for(RUN_ID, 2)
    assert first.artifact.content_hash != second.artifact.content_hash
    assert second.artifact.content_ref == content_ref_for(2)
    assert first.summary.reviewed == 1
    assert second.summary.reviewed == 2
    # The unreviewed layers are identical between versions.
    assert first.requirements[2] == second.requirements[2]


def test_the_builder_mutates_no_input() -> None:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    reviews = (_review(assessments[0]),)
    requirements_before = requirements.model_dump_json()
    assessments_before = tuple(item.model_dump_json() for item in assessments)
    reviews_before = tuple(item.model_dump_json() for item in reviews)

    build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )

    assert requirements.model_dump_json() == requirements_before
    assert tuple(item.model_dump_json() for item in assessments) == assessments_before
    assert tuple(item.model_dump_json() for item in reviews) == reviews_before
