"""Append-only review store: atomic writes, no overwrite, fail-closed loads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pydantic
import pytest
from conftest import populate_synthetic_golden_store

from bidfusion.bid_intelligence.matching import (
    RequirementKnowledgeAssessment,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.review import (
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewStoreConflictError,
    ReviewStoreIntegrityError,
    RunReviewStore,
    record_requirement_assessment_review,
)
from bidfusion.schemas.common import RequirementCategory, RequirementModality
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import ExtractionInfo, SourceLocator, SourceReference

BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _assessment(tmp_path: Path) -> RequirementKnowledgeAssessment:
    root = tmp_path / "golden"
    if not root.is_dir():
        populate_synthetic_golden_store(root)
    requirement = Requirement(
        requirement_id="REQ-000001",
        bid_id=BID_ID,
        original_text="The service MUST support Microsoft Sentinel.",
        modality=RequirementModality.MUST,
        category=RequirementCategory.TECHNICAL,
        confidence=0.9,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-001",
            filename="mtd-requirements.docx",
            document_hash="a" * 64,
            locator=SourceLocator(paragraph_id="p-1"),
            canonical_artifact_id="ART-20260804-000011",
        ),
        extraction=ExtractionInfo(method="rule", producer="x", producer_version="0.1.0"),
    )
    return assess_requirements((requirement,), load_claims_snapshot(root)).assessments[0]


def _review(
    assessment: RequirementKnowledgeAssessment,
    existing: tuple[RequirementAssessmentReview, ...] = (),
) -> RequirementAssessmentReview:
    return record_requirement_assessment_review(
        assessment,
        decision=ReviewDecision.CONFIRMED,
        reviewer="Alex Reviewer",
        rationale=None,
        reviewed_at=NOW,
        run_id="RUN-20260821-0001",
        existing=existing,
    )


def test_append_and_read_roundtrip_with_versioned_files(tmp_path: Path) -> None:
    store = RunReviewStore(tmp_path / "reviews")
    assessment = _assessment(tmp_path)
    first = _review(assessment)
    second = _review(assessment, existing=(first,))

    store.append_review(first)
    store.append_review(second)

    loaded = store.read_reviews()
    assert loaded == (first, second)
    files = sorted(path.name for path in (tmp_path / "reviews" / first.assessment_id).iterdir())
    assert files == ["review-v0001.json", "review-v0002.json"]


def test_an_existing_review_version_is_never_overwritten(tmp_path: Path) -> None:
    store = RunReviewStore(tmp_path / "reviews")
    review = _review(_assessment(tmp_path))
    store.append_review(review)

    with pytest.raises(ReviewStoreConflictError):
        store.append_review(review)
    assert store.read_reviews() == (review,)


def test_an_absent_root_is_an_empty_store(tmp_path: Path) -> None:
    assert RunReviewStore(tmp_path / "never-created").read_reviews() == ()


def test_a_corrupt_review_file_fails_the_whole_load_closed(tmp_path: Path) -> None:
    store = RunReviewStore(tmp_path / "reviews")
    review = _review(_assessment(tmp_path))
    store.append_review(review)
    target = tmp_path / "reviews" / review.assessment_id / "review-v0001.json"
    target.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ReviewStoreIntegrityError):
        store.read_reviews()


def test_a_file_whose_name_disagrees_with_its_content_fails_closed(tmp_path: Path) -> None:
    store = RunReviewStore(tmp_path / "reviews")
    review = _review(_assessment(tmp_path))
    store.append_review(review)
    directory = tmp_path / "reviews" / review.assessment_id
    (directory / "review-v0002.json").write_text(
        (directory / "review-v0001.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(ReviewStoreIntegrityError):
        store.read_reviews()


def test_foreign_entries_below_the_root_fail_closed(tmp_path: Path) -> None:
    store = RunReviewStore(tmp_path / "reviews")
    review = _review(_assessment(tmp_path))
    store.append_review(review)

    (tmp_path / "reviews" / "not-an-assessment-dir").mkdir()
    with pytest.raises(ReviewStoreIntegrityError):
        store.read_reviews()


def test_no_request_value_can_shape_a_store_path(tmp_path: Path) -> None:
    """Path segments come only from validated contract fields: a review
    with a traversal-shaped assessment id cannot even be constructed."""
    review = _review(_assessment(tmp_path))
    with pytest.raises(pydantic.ValidationError):
        RequirementAssessmentReview.model_validate(
            {**review.model_dump(), "assessment_id": "../escape"}
        )
