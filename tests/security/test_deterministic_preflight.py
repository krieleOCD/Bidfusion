"""Adversarial tests for the deterministic Security Gate preflight slice."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest
from pydantic import ValidationError

from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    PreflightAssessment,
    SecurityCheckResult,
    SecurityCheckStatus,
    Severity,
)
from bidfusion.security import (
    ArtifactContentMismatchError,
    DeterministicPreflightScanner,
    PreflightConfig,
    PreflightInputError,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260729-0001"
DOCUMENT_ID = "DOC-003"
ASSESSED_AT = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
CLEAN_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


def raw_artifact(
    content: bytes,
    *,
    artifact_type: ArtifactType = ArtifactType.RAW_DOCUMENT,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id="ART-20260729-000001",
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=artifact_type,
        schema_version="1.0.0",
        content_ref="artifacts/ART-20260729-000001",
        content_hash=sha256(content).hexdigest(),
    )


def office_document(
    *,
    document_path: str = "word/document.xml",
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types />")
        archive.writestr(document_path, b"<document>safe</document>")
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def assess(
    content: bytes,
    filename: str,
    *,
    scanner: DeterministicPreflightScanner | None = None,
) -> PreflightAssessment:
    active_scanner = scanner or DeterministicPreflightScanner()
    return active_scanner.assess(
        artifact=raw_artifact(content),
        document_id=DOCUMENT_ID,
        filename=filename,
        content=content,
        assessed_at=ASSESSED_AT,
    )


def check(assessment: PreflightAssessment, name: str) -> SecurityCheckResult:
    return next(result for result in assessment.checks if result.check == name)


def test_clean_pdf_produces_bound_observations_but_no_gate_decision() -> None:
    assessment = assess(CLEAN_PDF, "request.pdf")

    assert assessment.artifact.content_hash == sha256(CLEAN_PDF).hexdigest()
    assert assessment.content_hash == assessment.artifact.content_hash
    assert assessment.bid_id == BID_ID
    assert assessment.document_id == DOCUMENT_ID
    assert assessment.completed_successfully
    assert not assessment.requires_gate_attention
    assert check(assessment, "mime_type").details["detected_mime"] == "application/pdf"
    assert check(assessment, "pdf_javascript").status is SecurityCheckStatus.PASS
    assert not hasattr(assessment, "verdict")
    assert not hasattr(assessment, "allows_processing")


def test_assessment_and_nested_details_are_immutable() -> None:
    assessment = assess(CLEAN_PDF, "request.pdf")

    with pytest.raises(ValidationError, match="frozen"):
        assessment.scanner = "changed"
    with pytest.raises(TypeError, match="frozen mapping"):
        check(assessment, "mime_type").details["detected_mime"] = "text/plain"


def test_content_hash_mismatch_fails_before_an_assessment_can_be_created() -> None:
    scanner = DeterministicPreflightScanner()
    artifact = raw_artifact(b"original bytes")

    with pytest.raises(ArtifactContentMismatchError, match="content hash"):
        scanner.assess(
            artifact=artifact,
            document_id=DOCUMENT_ID,
            filename="request.pdf",
            content=CLEAN_PDF,
            assessed_at=ASSESSED_AT,
        )


def test_non_raw_artifact_is_rejected() -> None:
    scanner = DeterministicPreflightScanner()

    with pytest.raises(PreflightInputError, match="raw_document"):
        scanner.assess(
            artifact=raw_artifact(CLEAN_PDF, artifact_type=ArtifactType.OCR_RESULT),
            document_id=DOCUMENT_ID,
            filename="request.pdf",
            content=CLEAN_PDF,
            assessed_at=ASSESSED_AT,
        )


@pytest.mark.parametrize("filename", ["request.exe", "request.js", "request.ps1"])
def test_blocked_extension_fails_even_when_bytes_are_a_valid_pdf(filename: str) -> None:
    assessment = assess(CLEAN_PDF, filename)

    result = check(assessment, "extension_mime")
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is Severity.CRITICAL
    assert assessment.requires_gate_attention


def test_extension_and_magic_byte_mismatch_is_explicit() -> None:
    assessment = assess(CLEAN_PDF, "request.docx")

    result = check(assessment, "extension_mime")
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is Severity.HIGH
    assert result.details["detected_mime"] == "application/pdf"


def test_unknown_binary_type_is_not_treated_as_safe() -> None:
    assessment = assess(b"\x00\x01\x02\x03unrecognized", "request.bin")

    assert check(assessment, "mime_type").status is SecurityCheckStatus.UNKNOWN
    assert check(assessment, "structural_integrity").status is SecurityCheckStatus.UNKNOWN
    assert not assessment.completed_successfully
    assert assessment.requires_gate_attention


def test_oversized_file_is_a_critical_failure() -> None:
    scanner = DeterministicPreflightScanner(
        config=PreflightConfig(max_file_size_bytes=10),
    )
    assessment = assess(CLEAN_PDF, "request.pdf", scanner=scanner)

    result = check(assessment, "file_size")
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is Severity.CRITICAL


@pytest.mark.parametrize(
    ("indicator", "check_name"),
    [
        (b"/JavaScript", "pdf_javascript"),
        (b"/EmbeddedFile", "pdf_embedded_files"),
        (b"/Encrypt", "encryption"),
    ],
)
def test_active_pdf_features_are_reported_as_failures(
    indicator: bytes,
    check_name: str,
) -> None:
    content = b"%PDF-1.7\n" + indicator + b"\n%%EOF"
    assessment = assess(content, "request.pdf")

    result = check(assessment, check_name)
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is Severity.HIGH


def test_clean_docx_completes_all_applicable_archive_checks() -> None:
    content = office_document()
    assessment = assess(content, "request.docx")

    assert check(assessment, "mime_type").status is SecurityCheckStatus.PASS
    assert check(assessment, "structural_integrity").status is SecurityCheckStatus.PASS
    assert check(assessment, "archive_limits").status is SecurityCheckStatus.PASS
    assert check(assessment, "macro_detection").status is SecurityCheckStatus.PASS
    assert check(assessment, "embedded_objects").status is SecurityCheckStatus.PASS
    assert assessment.completed_successfully


@pytest.mark.parametrize(
    ("entry_name", "check_name", "severity"),
    [
        ("word/vbaProject.bin", "macro_detection", Severity.CRITICAL),
        ("word/embeddings/oleObject1.bin", "embedded_objects", Severity.HIGH),
    ],
)
def test_office_active_content_is_reported(
    entry_name: str,
    check_name: str,
    severity: Severity,
) -> None:
    content = office_document(extra_entries={entry_name: b"active content"})
    assessment = assess(content, "request.docx")

    result = check(assessment, check_name)
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is severity


def test_corrupt_zip_is_never_silently_skipped() -> None:
    content = b"PK\x03\x04not-a-valid-central-directory"
    assessment = assess(content, "request.docx")

    assert check(assessment, "mime_type").status is SecurityCheckStatus.UNKNOWN
    assert check(assessment, "structural_integrity").status is SecurityCheckStatus.FAIL
    assert check(assessment, "archive_limits").status is SecurityCheckStatus.ERROR
    assert assessment.requires_gate_attention


def test_high_archive_compression_ratio_is_reported() -> None:
    content = office_document(
        extra_entries={"word/media/repeated.bin": b"A" * 20_000},
    )
    scanner = DeterministicPreflightScanner(
        config=PreflightConfig(max_archive_compression_ratio=2.0),
    )
    assessment = assess(content, "request.docx", scanner=scanner)

    result = check(assessment, "archive_limits")
    assert result.status is SecurityCheckStatus.FAIL
    assert result.severity is Severity.HIGH


def test_security_check_contract_rejects_ambiguous_status_severity_combinations() -> None:
    with pytest.raises(ValidationError, match="require a severity"):
        SecurityCheckResult(
            check="macro_detection",
            status=SecurityCheckStatus.FAIL,
            message="Macro found.",
        )
    with pytest.raises(ValidationError, match="cannot carry a severity"):
        SecurityCheckResult(
            check="macro_detection",
            status=SecurityCheckStatus.PASS,
            severity=Severity.LOW,
            message="No macro found.",
        )


def test_preflight_assessment_rejects_duplicate_check_names() -> None:
    assessment = assess(CLEAN_PDF, "request.pdf")
    data = assessment.model_dump()
    data["checks"] = [assessment.checks[0], assessment.checks[0]]

    with pytest.raises(ValidationError, match="duplicate check names"):
        PreflightAssessment.model_validate(data)
