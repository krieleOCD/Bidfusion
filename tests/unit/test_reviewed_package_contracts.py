"""Contract invariants of the persisted Reviewed Working Package."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pydantic
import pytest
from conftest import synthetic_golden_claims

from bidfusion.bid_intelligence.matching import (
    ClaimsSnapshot,
    KnowledgeStoreState,
    assess_requirements,
)
from bidfusion.bid_intelligence.review import (
    PackageReviewState,
    PackageReviewSummary,
    ReviewDecision,
    ReviewedWorkingPackage,
    build_reviewed_working_package,
    package_id_for,
    record_requirement_assessment_review,
    summarize_entries,
)
from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import ProcessingStatus, RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement, RequirementExtractionResult
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference
from bidfusion.shared.payloads import seal_artifact

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
    ("The provider MUST support Microsoft Defender XDR investigations.", RequirementModality.MUST),
    ("The provider SHOULD describe its catering arrangements.", RequirementModality.SHOULD),
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


def _extraction_result() -> RequirementExtractionResult:
    items = tuple(
        _requirement(sequence, text, modality)
        for sequence, (text, modality) in enumerate(_TEXTS, start=1)
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


def _package(reviewed: int = 1) -> ReviewedWorkingPackage:
    requirements = _extraction_result()
    snapshot = ClaimsSnapshot(state=KnowledgeStoreState.AVAILABLE, claims=synthetic_golden_claims())
    assessments = assess_requirements(requirements.requirements, snapshot).assessments
    reviews = tuple(
        record_requirement_assessment_review(
            assessment,
            decision=ReviewDecision.CONFIRMED,
            reviewer="Alex Reviewer",
            rationale=None,
            reviewed_at=NOW,
            run_id=RUN_ID,
        )
        for assessment in assessments[:reviewed]
    )
    return build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=1,
        artifact_id="ART-20260821-000099",
        created_at=NOW,
    )


def test_a_valid_package_constructs_and_is_frozen() -> None:
    package = _package()

    assert package.package_review_state is PackageReviewState.REVIEW_INCOMPLETE
    assert package.summary.total_requirements == len(_TEXTS)
    with pytest.raises(pydantic.ValidationError):
        package.package_version = 2


def test_the_summary_must_equal_the_recount_of_the_entries() -> None:
    package = _package()
    assert package.summary == summarize_entries(package.requirements)

    payload = package.model_dump(mode="json")
    payload["summary"]["pending"] += 1
    payload["summary"]["total_requirements"] += 1
    with pytest.raises(pydantic.ValidationError):
        ReviewedWorkingPackage.model_validate(payload)


def test_the_package_state_must_follow_from_the_pending_count() -> None:
    package = _package()

    payload = package.model_dump(mode="json")
    payload["package_review_state"] = PackageReviewState.REVIEW_COMPLETE.value
    with pytest.raises(pydantic.ValidationError):
        ReviewedWorkingPackage.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda p: p.update(package_id="RWP-aaaaaaaaaaaa"), "underived package id"),
        (lambda p: p.update(package_id="../escape"), "traversal-shaped package id"),
        (lambda p: p.update(package_version=0), "zero package version"),
        (lambda p: p.update(created_at="2026-08-21T12:00:00"), "naive timestamp"),
        (lambda p: p.update(bid_id="BID-9999-999999"), "foreign bid"),
        (lambda p: p.update(run_id="RUN-99999999-9999"), "foreign run"),
        (lambda p: p.update(extra_field="x"), "undeclared field"),
        (lambda p: p["artifact"].update(artifact_type="working_package"), "wrong artifact type"),
        (
            lambda p: p["source_requirements"].update(artifact_type="canonical_document"),
            "wrong source artifact type",
        ),
        (
            lambda p: p["requirements"].append(p["requirements"][0]),
            "duplicate requirement entry",
        ),
        (
            lambda p: p["requirements"][0]["machine"].update(assessment_version="9.9.9"),
            "assessment version drift",
        ),
        (
            lambda p: p["requirements"][0]["rfp"]["source"].update(bid_id="BID-9999-999999"),
            "foreign requirement source",
        ),
    ],
)
def test_malformed_packages_fail_closed(mutate: Any, label: str) -> None:
    payload = _package().model_dump(mode="json")
    mutate(payload)
    with pytest.raises(pydantic.ValidationError):
        ReviewedWorkingPackage.model_validate(payload)


def test_matched_entries_must_reference_a_claim_and_evidence() -> None:
    package = _package()
    matched = next(
        entry
        for entry in package.requirements
        if entry.machine.match_status is not None and entry.machine.match_status.value == "MATCHED"
    )
    index = package.requirements.index(matched)

    payload = package.model_dump(mode="json")
    payload["requirements"][index]["machine"]["matched_claim_id"] = None
    with pytest.raises(pydantic.ValidationError):
        ReviewedWorkingPackage.model_validate(payload)

    payload = package.model_dump(mode="json")
    payload["requirements"][index]["golden"]["evidence_refs"] = []
    with pytest.raises(pydantic.ValidationError):
        ReviewedWorkingPackage.model_validate(payload)


def test_human_review_entries_are_bounded_and_timezone_aware() -> None:
    package = _package()
    reviewed_index = next(
        index for index, entry in enumerate(package.requirements) if entry.human_review is not None
    )

    for override in (
        {"reviewer": "R" * 121},
        {"rationale": "r" * 2001},
        {"reviewed_at": "2026-08-21T12:00:00"},
        {"review_id": "not-an-id"},
        {"review_version": 0},
    ):
        payload = package.model_dump(mode="json")
        payload["requirements"][reviewed_index]["human_review"].update(override)
        with pytest.raises(pydantic.ValidationError):
            ReviewedWorkingPackage.model_validate(payload)


def test_summary_counts_must_be_internally_consistent() -> None:
    with pytest.raises(pydantic.ValidationError):
        PackageReviewSummary(
            total_requirements=3,
            reviewed=1,
            pending=1,
            confirmed_candidate=1,
            rejected_candidate=0,
            needs_clarification=0,
        )
    with pytest.raises(pydantic.ValidationError):
        PackageReviewSummary(
            total_requirements=2,
            reviewed=2,
            pending=0,
            confirmed_candidate=1,
            rejected_candidate=0,
            needs_clarification=0,
        )


def test_package_ids_are_deterministically_derived() -> None:
    first = package_id_for(RUN_ID, 1)
    second = package_id_for(RUN_ID, 2)

    assert first == package_id_for(RUN_ID, 1)
    assert first != second
    assert first.startswith("RWP-")


def test_the_three_trust_layers_stay_separate_fields() -> None:
    package = _package()
    entry = next(item for item in package.requirements if item.human_review is not None)

    # Machine candidate, golden claim state, and human decision are three
    # independently populated fields — none is derived from another.
    assert entry.machine.match_status is not None
    assert entry.golden.claim_status is not None
    assert entry.human_review is not None
    assert entry.machine.match_status.value != entry.human_review.decision.value
    dumped = entry.model_dump(mode="json")
    assert set(dumped) == {"rfp", "machine", "golden", "human_review"}
