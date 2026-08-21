"""Reviewed package store: atomic versioned writes, fail-closed verified loads."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import synthetic_golden_claims

from bidfusion.bid_intelligence.matching import (
    ClaimsSnapshot,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    assess_requirements,
)
from bidfusion.bid_intelligence.review import (
    PackageStoreConflictError,
    PackageStoreIntegrityError,
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewedPackageStore,
    ReviewedWorkingPackage,
    build_reviewed_working_package,
    record_requirement_assessment_review,
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


def _assessed(
    requirements: RequirementExtractionResult,
) -> tuple[RequirementKnowledgeAssessment, ...]:
    snapshot = ClaimsSnapshot(state=KnowledgeStoreState.AVAILABLE, claims=synthetic_golden_claims())
    return assess_requirements(requirements.requirements, snapshot).assessments


def _package(
    version: int = 1,
    reviews: tuple[RequirementAssessmentReview, ...] | None = None,
) -> ReviewedWorkingPackage:
    requirements = _extraction_result()
    assessments = _assessed(requirements)
    if reviews is None:
        reviews = (
            record_requirement_assessment_review(
                assessments[0],
                decision=ReviewDecision.CONFIRMED,
                reviewer="Alex Reviewer",
                rationale="Fits this bid.",
                reviewed_at=NOW,
                run_id=RUN_ID,
            ),
        )
    return build_reviewed_working_package(
        requirements,
        assessments=assessments,
        reviews=reviews,
        package_version=version,
        artifact_id=f"ART-20260821-{9000 + version:06d}",
        created_at=NOW,
    )


def test_append_and_read_roundtrip_with_versioned_files(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    package = _package()

    store.append_package(package)

    assert store.read_packages() == (package,)
    assert store.read_latest() == package
    files = sorted(path.name for path in (tmp_path / "reviewed-packages").iterdir())
    assert files == [
        "reviewed-working-package-v0001.audit.json",
        "reviewed-working-package-v0001.payload.json",
    ]
    for name in files:
        mode = stat.S_IMODE((tmp_path / "reviewed-packages" / name).stat().st_mode)
        assert mode == 0o600


def test_versions_accumulate_and_the_first_version_stays_intact(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    first = _package(version=1)
    store.append_package(first)
    first_payload = (
        tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.payload.json"
    ).read_bytes()

    assert store.next_version() == 2
    second = _package(version=2, reviews=())
    store.append_package(second)

    assert store.read_packages() == (first, second)
    assert store.read_latest() == second
    assert first != second
    assert (
        tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.payload.json"
    ).read_bytes() == first_payload


def test_an_existing_package_version_is_never_overwritten(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    package = _package()
    store.append_package(package)

    with pytest.raises(PackageStoreConflictError):
        store.append_package(package)
    assert store.read_packages() == (package,)


def test_an_absent_root_is_an_empty_store(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "never-created")
    assert store.read_packages() == ()
    assert store.read_latest() is None
    assert store.next_version() == 1


def test_corrupt_json_fails_the_whole_load_closed(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())
    target = tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.audit.json"
    target.write_text("{ not json", encoding="utf-8")

    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        (b'"decision": "CONFIRMED"', b'"decision": "REJECTED"'),
        (b"Alex Reviewer", b"Someone Else!"),
        (b"Microsoft Sentinel", b"Different Vendor"),
        (b'"section_id": "SEC-0002"', b'"section_id": "SEC-0009"'),
        (b"Fits this bid.", b"Does not fit."),
    ],
)
def test_tampered_audit_content_is_never_rendered_valid(
    tmp_path: Path, needle: bytes, replacement: bytes
) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())
    target = tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.audit.json"
    original = target.read_bytes()
    assert needle in original
    target.write_bytes(original.replace(needle, replacement))

    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()
    with pytest.raises(PackageStoreIntegrityError):
        store.read_latest()


def test_a_removed_review_in_the_audit_fails_closed(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())
    target = tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.audit.json"
    original = target.read_text(encoding="utf-8")
    start = original.index('"human_review": {')
    end = original.index("},", start) + 1
    target.write_text(original[:start] + '"human_review": null' + original[end:], encoding="utf-8")

    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()


def test_a_tampered_payload_file_fails_closed(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())
    target = tmp_path / "reviewed-packages" / "reviewed-working-package-v0001.payload.json"
    target.write_bytes(target.read_bytes().replace(b"CONFIRMED", b"REJECTED9"))

    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()


def test_stray_files_and_missing_pairs_fail_closed(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())

    stray = tmp_path / "reviewed-packages" / "notes.txt"
    stray.write_text("x", encoding="utf-8")
    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()
    stray.unlink()

    (tmp_path / "reviewed-packages" / "reviewed-working-package-v0002.payload.json").write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()


def test_a_symlinked_store_entry_fails_closed(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    store.append_package(_package())
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "reviewed-packages" / "reviewed-working-package-v0002.audit.json"
    link.symlink_to(outside)

    with pytest.raises(PackageStoreIntegrityError):
        store.read_packages()


def test_a_content_ref_that_disagrees_with_the_version_is_refused(tmp_path: Path) -> None:
    """No package whose envelope points outside its controlled filename is
    ever written; the store derives the path from the validated version
    field only and cross-checks the envelope."""
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    package = _package()
    payload = package.model_dump(mode="json")
    payload["artifact"]["content_ref"] = "../escape.payload.json"
    crafted = ReviewedWorkingPackage.model_validate(payload)

    with pytest.raises(PackageStoreIntegrityError):
        store.append_package(crafted)
    assert not (tmp_path / "reviewed-packages").exists()


def test_an_unsealed_package_is_refused_before_any_write(tmp_path: Path) -> None:
    store = ReviewedPackageStore(tmp_path / "reviewed-packages")
    package = _package()
    payload = package.model_dump(mode="json")
    payload["artifact"]["content_hash"] = "d" * 64
    crafted = ReviewedWorkingPackage.model_validate(payload)

    with pytest.raises(ValueError, match="content hash"):
        store.append_package(crafted)
    assert not (tmp_path / "reviewed-packages").exists()
