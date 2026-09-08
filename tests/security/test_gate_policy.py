"""Adversarial tests for the versioned MVP package gate policy."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    PreflightAssessment,
    SecurityCheckResult,
    SecurityCheckStatus,
    SecurityClearedArtifact,
    SecurityManualReview,
    SecurityResult,
    SecurityReviewDisposition,
    SecurityVerdict,
    Severity,
)
from bidfusion.security import (
    MVP_GATE_POLICY_ID,
    PackageGateDecision,
    PackageGateResult,
    decide_document,
    decide_package,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
ASSESSED_AT = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
CONTENT = b"synthetic bytes"


def artifact(
    sequence: int,
    *,
    bid_id: str = BID_ID,
    run_id: str = RUN_ID,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=f"ART-20260804-{sequence:06d}",
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref=f"package/document-{sequence}",
        content_hash=sha256(CONTENT).hexdigest(),
    )


def check(
    status: SecurityCheckStatus,
    *,
    name: str = "mime_type",
    severity: Severity | None = None,
) -> SecurityCheckResult:
    return SecurityCheckResult(
        check=name,
        status=status,
        message="Synthetic check outcome.",
        severity=severity,
    )


def assessment(
    checks: tuple[SecurityCheckResult, ...],
    *,
    sequence: int = 1,
) -> PreflightAssessment:
    return PreflightAssessment(
        bid_id=BID_ID,
        document_id=f"DOC-{sequence:03d}",
        artifact=artifact(sequence),
        content_hash=sha256(CONTENT).hexdigest(),
        scanner="bidfusion-deterministic-preflight",
        scanner_version="1.0.0",
        assessed_at=ASSESSED_AT,
        checks=checks,
    )


def result_with_verdict(verdict: SecurityVerdict, *, sequence: int = 1) -> SecurityResult:
    return SecurityResult(
        bid_id=BID_ID,
        document_id=f"DOC-{sequence:03d}",
        artifact=artifact(sequence),
        content_hash=sha256(CONTENT).hexdigest(),
        verdict=verdict,
        scanner="bidfusion-deterministic-preflight",
        scanner_version="1.0.0",
        policy_version=MVP_GATE_POLICY_ID,
        decided_at=ASSESSED_AT,
    )


def registered_for(
    *results: SecurityResult,
) -> tuple[tuple[str, ArtifactReference], ...]:
    return tuple((result.document_id, result.artifact) for result in results)


def decide(
    results: tuple[SecurityResult, ...],
    *,
    registered: tuple[tuple[str, ArtifactReference], ...] | None = None,
    intake_rejections: tuple[str, ...] = (),
) -> PackageGateResult:
    return decide_package(
        results,
        registered=registered_for(*results) if registered is None else registered,
        bid_id=BID_ID,
        run_id=RUN_ID,
        intake_rejections=intake_rejections,
    )


def test_fully_passing_assessment_maps_to_allow_with_versioned_policy() -> None:
    decision = decide_document(
        assessment(
            (
                check(SecurityCheckStatus.PASS),
                check(SecurityCheckStatus.NOT_APPLICABLE, name="macro_detection"),
            )
        )
    )

    assert decision.verdict is SecurityVerdict.ALLOW
    assert decision.findings == ()
    assert decision.policy_version == "bidfusion-mvp-local-gate:0.1.0"
    assert decision.decided_at == ASSESSED_AT


def test_critical_failure_blocks_the_document() -> None:
    decision = decide_document(
        assessment(
            (
                check(SecurityCheckStatus.PASS),
                check(
                    SecurityCheckStatus.FAIL,
                    name="extension_mime",
                    severity=Severity.CRITICAL,
                ),
            )
        )
    )

    assert decision.verdict is SecurityVerdict.BLOCK
    assert decision.findings[0].check == "extension_mime"
    assert decision.findings[0].severity is Severity.CRITICAL


@pytest.mark.parametrize(
    ("status", "severity", "expected_finding_severity"),
    [
        (SecurityCheckStatus.FAIL, Severity.HIGH, Severity.HIGH),
        (SecurityCheckStatus.ERROR, None, Severity.HIGH),
        (SecurityCheckStatus.UNKNOWN, None, Severity.MEDIUM),
    ],
)
def test_non_clean_outcomes_fail_closed_into_manual_review(
    status: SecurityCheckStatus,
    severity: Severity | None,
    expected_finding_severity: Severity,
) -> None:
    decision = decide_document(
        assessment(
            (
                check(SecurityCheckStatus.PASS),
                check(status, name="encryption", severity=severity),
            )
        )
    )

    assert decision.verdict is SecurityVerdict.MANUAL_REVIEW
    assert decision.findings[0].severity is expected_finding_severity


def test_cleared_package_requires_exactly_one_allow_per_registered_document() -> None:
    results = (
        result_with_verdict(SecurityVerdict.ALLOW, sequence=1),
        result_with_verdict(SecurityVerdict.ALLOW, sequence=2),
    )

    package = decide(results)

    assert package.decision is PackageGateDecision.CLEARED
    assert package.allows_processing
    assert package.policy_id == MVP_GATE_POLICY_ID
    assert package.reasons == ()
    assert {cleared.document_id for cleared in package.cleared} == {"DOC-001", "DOC-002"}
    for cleared in package.cleared:
        assert cleared.security_result.verdict is SecurityVerdict.ALLOW


def test_single_block_blocks_the_whole_package() -> None:
    results = (
        result_with_verdict(SecurityVerdict.ALLOW, sequence=1),
        result_with_verdict(SecurityVerdict.BLOCK, sequence=2),
        result_with_verdict(SecurityVerdict.MANUAL_REVIEW, sequence=3),
    )

    package = decide(results)

    assert package.decision is PackageGateDecision.BLOCKED
    assert not package.allows_processing
    assert package.cleared == ()
    assert any("DOC-002" in reason for reason in package.reasons)


@pytest.mark.parametrize(
    "verdict",
    [SecurityVerdict.MANUAL_REVIEW, SecurityVerdict.QUARANTINE],
)
def test_review_and_quarantine_keep_the_package_in_review(verdict: SecurityVerdict) -> None:
    results = (
        result_with_verdict(SecurityVerdict.ALLOW, sequence=1),
        result_with_verdict(verdict, sequence=2),
    )

    package = decide(results)

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()


def test_missing_document_decisions_fail_closed() -> None:
    allowed = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    silent = result_with_verdict(SecurityVerdict.ALLOW, sequence=2)

    package = decide((allowed,), registered=registered_for(allowed, silent))

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()
    assert any("no security decision" in reason for reason in package.reasons)


def test_empty_package_is_never_cleared() -> None:
    package = decide((), registered=())

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()


def test_unexpected_decisions_for_unregistered_documents_fail_closed() -> None:
    registered_result = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    stray = result_with_verdict(SecurityVerdict.ALLOW, sequence=9)

    package = decide(
        (registered_result, stray),
        registered=registered_for(registered_result),
    )

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()
    assert any("unregistered document DOC-009" in reason for reason in package.reasons)


def test_duplicate_registered_document_ids_fail_closed() -> None:
    result = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    registered = (
        ("DOC-001", artifact(1)),
        ("DOC-001", artifact(2)),
    )

    package = decide((result,), registered=registered)

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert any("duplicate document id DOC-001" in reason for reason in package.reasons)


def test_duplicate_registered_artifact_ids_fail_closed() -> None:
    result = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    registered = (
        ("DOC-001", artifact(1)),
        ("DOC-002", artifact(1)),
    )

    package = decide((result,), registered=registered)

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert any("duplicate artifact id" in reason for reason in package.reasons)


@pytest.mark.parametrize(
    "foreign",
    [
        artifact(1, bid_id="BID-2026-999999"),
        artifact(1, run_id="RUN-20260101-0001"),
    ],
)
def test_registered_artifacts_from_foreign_bids_or_runs_fail_closed(
    foreign: ArtifactReference,
) -> None:
    package = decide((), registered=(("DOC-001", foreign),))

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert any("foreign bid or run" in reason for reason in package.reasons)


def test_swapped_artifacts_between_documents_fail_closed() -> None:
    first = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    second = result_with_verdict(SecurityVerdict.ALLOW, sequence=2)
    swapped_registration = (
        ("DOC-001", second.artifact),
        ("DOC-002", first.artifact),
    )

    package = decide((first, second), registered=swapped_registration)

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()
    swapped_reasons = [
        reason for reason in package.reasons if "mismatched or swapped artifact" in reason
    ]
    assert len(swapped_reasons) == 2


def test_duplicate_and_contradictory_decisions_fail_closed() -> None:
    allowed = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)
    duplicate = decide(
        (allowed, allowed),
        registered=registered_for(allowed),
    )
    contradictory = decide(
        (allowed, result_with_verdict(SecurityVerdict.BLOCK, sequence=1)),
        registered=registered_for(allowed),
    )

    assert duplicate.decision is PackageGateDecision.REVIEW_REQUIRED
    assert any("duplicate security decisions" in reason for reason in duplicate.reasons)
    assert contradictory.decision is PackageGateDecision.BLOCKED
    assert any("contradictory security decisions" in reason for reason in contradictory.reasons)
    assert contradictory.cleared == ()


def test_intake_rejections_keep_the_package_in_review() -> None:
    result = result_with_verdict(SecurityVerdict.ALLOW, sequence=1)

    package = decide(
        (result,),
        intake_rejections=("payload.bin: file size exceeds the intake limit",),
    )

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()
    assert any("rejected at intake" in reason for reason in package.reasons)


def test_released_manual_review_is_not_cleared_by_the_mvp_policy() -> None:
    released = SecurityResult(
        bid_id=BID_ID,
        document_id="DOC-001",
        artifact=artifact(1),
        content_hash=sha256(CONTENT).hexdigest(),
        verdict=SecurityVerdict.MANUAL_REVIEW,
        scanner="bidfusion-deterministic-preflight",
        scanner_version="1.0.0",
        policy_version=MVP_GATE_POLICY_ID,
        decided_at=ASSESSED_AT,
        manual_review=SecurityManualReview(
            review_id="REV-000001",
            reviewer_id="ACT-0001",
            disposition=SecurityReviewDisposition.RELEASED,
            decided_at=ASSESSED_AT,
            rationale="Synthetic audited release.",
        ),
    )

    package = decide((released,))

    assert package.decision is PackageGateDecision.REVIEW_REQUIRED
    assert package.cleared == ()


def test_pending_manual_review_cannot_construct_a_clearance_contract() -> None:
    pending = result_with_verdict(SecurityVerdict.MANUAL_REVIEW)

    with pytest.raises(ValidationError, match="does not permit processing"):
        SecurityClearedArtifact(
            artifact=pending.artifact,
            document_id=pending.document_id,
            security_result=pending,
        )
