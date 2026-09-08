"""Versioned MVP Security Gate policy: assessments to package-level release.

This is the explicit, deliberately narrow first gate-policy slice. It turns
deterministic ``PreflightAssessment`` observations into per-document
``SecurityResult`` decisions and aggregates them against the **exact
registered set** of documents and raw artifacts:

- at least one ``BLOCK``: the whole package is blocked;
- any anomaly in the registration mapping — missing, duplicate,
  contradictory, or unexpected decisions, swapped or foreign artifacts,
  intake rejections — keeps the whole package in review (fail closed);
- only when exactly one matching ``ALLOW`` decision exists per registered
  document and artifact: ``SecurityClearedArtifact`` handoffs are
  constructed.

There is no partial processing of a package in this MVP, and no manual
release workflow: an audited release path remains future gate work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import SecurityVerdict, Severity
from bidfusion.schemas.ids import BidId, DocumentId, RunId
from bidfusion.schemas.security import (
    PreflightAssessment,
    SecurityCheckResult,
    SecurityCheckStatus,
    SecurityClearedArtifact,
    SecurityFinding,
    SecurityResult,
)

RegisteredArtifacts = tuple[tuple[DocumentId, ArtifactReference], ...]

MVP_GATE_POLICY_NAME = "bidfusion-mvp-local-gate"
MVP_GATE_POLICY_VERSION = "0.1.0"
MVP_GATE_POLICY_ID = f"{MVP_GATE_POLICY_NAME}:{MVP_GATE_POLICY_VERSION}"

_FINDING_SEVERITY_FOR_STATUS = {
    SecurityCheckStatus.ERROR: Severity.HIGH,
    SecurityCheckStatus.UNKNOWN: Severity.MEDIUM,
}


class PackageGateDecision(StrEnum):
    """Package-level release decision of the MVP gate policy."""

    CLEARED = "CLEARED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PackageGateResult:
    """Aggregated gate outcome for one registered RFP package."""

    decision: PackageGateDecision
    policy_id: str
    document_results: tuple[SecurityResult, ...]
    cleared: tuple[SecurityClearedArtifact, ...]
    reasons: tuple[str, ...]

    @property
    def allows_processing(self) -> bool:
        """Whether downstream document understanding may start."""
        return self.decision is PackageGateDecision.CLEARED


def decide_document(
    assessment: PreflightAssessment,
    *,
    decided_at: datetime | None = None,
) -> SecurityResult:
    """Apply the versioned MVP policy to one deterministic assessment.

    Mapping: any ``FAIL`` with ``CRITICAL`` severity blocks the document;
    any other ``FAIL``, ``ERROR``, or ``UNKNOWN`` check demands manual
    review (fail closed); only a fully passing assessment maps to ``ALLOW``.
    """
    has_critical_failure = any(
        check.status is SecurityCheckStatus.FAIL and check.severity is Severity.CRITICAL
        for check in assessment.checks
    )
    if has_critical_failure:
        verdict = SecurityVerdict.BLOCK
    elif assessment.requires_gate_attention:
        verdict = SecurityVerdict.MANUAL_REVIEW
    else:
        verdict = SecurityVerdict.ALLOW

    return SecurityResult(
        bid_id=assessment.bid_id,
        document_id=assessment.document_id,
        artifact=assessment.artifact,
        content_hash=assessment.content_hash,
        verdict=verdict,
        findings=tuple(
            _finding_for(check)
            for check in assessment.checks
            if check.status
            in (SecurityCheckStatus.FAIL, SecurityCheckStatus.ERROR, SecurityCheckStatus.UNKNOWN)
        ),
        scanner=assessment.scanner,
        scanner_version=assessment.scanner_version,
        policy_version=MVP_GATE_POLICY_ID,
        decided_at=decided_at or assessment.assessed_at,
    )


def decide_package(
    document_results: tuple[SecurityResult, ...],
    *,
    registered: RegisteredArtifacts,
    bid_id: BidId,
    run_id: RunId,
    intake_rejections: tuple[str, ...] = (),
) -> PackageGateResult:
    """Aggregate per-document decisions against the exact registered set.

    ``registered`` is the exact intake output: one ``(document_id,
    raw ArtifactReference)`` pair per admitted document. The package can
    only be ``CLEARED`` when exactly one matching ``ALLOW`` decision exists
    per registered pair; every mapping anomaly fails closed into review.
    """
    reasons: list[str] = []

    if not registered:
        reasons.append("the package contains no registered documents")
    reasons.extend(
        f"file rejected at intake (fail closed): {rejection}" for rejection in intake_rejections
    )

    registered_ids = [document_id for document_id, _ in registered]
    duplicate_ids = sorted({item for item in registered_ids if registered_ids.count(item) > 1})
    reasons.extend(f"registration contains duplicate document id {item}" for item in duplicate_ids)
    artifact_ids = [artifact.artifact_id for _, artifact in registered]
    duplicate_artifacts = sorted({item for item in artifact_ids if artifact_ids.count(item) > 1})
    reasons.extend(
        f"registration contains duplicate artifact id {item}" for item in duplicate_artifacts
    )
    for document_id, artifact in registered:
        if artifact.bid_id != bid_id or artifact.run_id != run_id:
            reasons.append(f"registered document {document_id} references a foreign bid or run")

    results_by_document: dict[str, list[SecurityResult]] = {}
    for result in document_results:
        results_by_document.setdefault(result.document_id, []).append(result)

    registered_by_id = dict(registered)
    for document_id, results in sorted(results_by_document.items()):
        if document_id not in registered_by_id:
            reasons.append(f"unexpected security decision for unregistered document {document_id}")
        if len(results) > 1:
            verdicts = {result.verdict for result in results}
            kind = "contradictory" if len(verdicts) > 1 else "duplicate"
            reasons.append(f"{kind} security decisions for document {document_id} (fail closed)")

    matched: list[SecurityResult] = []
    for document_id, artifact in registered:
        results = results_by_document.get(document_id, [])
        if not results:
            reasons.append(f"document {document_id} has no security decision (fail closed)")
            continue
        if len(results) > 1:
            continue  # already reported above; never usable for clearance
        result = results[0]
        if result.artifact != artifact or result.bid_id != bid_id:
            reasons.append(
                f"security decision for document {document_id} does not reference "
                "the registered artifact (mismatched or swapped artifact)"
            )
            continue
        matched.append(result)
        if result.verdict is not SecurityVerdict.ALLOW:
            reasons.append(f"document {document_id} has verdict {result.verdict.value}")

    blocked = any(result.verdict is SecurityVerdict.BLOCK for result in document_results)
    if blocked:
        decision = PackageGateDecision.BLOCKED
    elif reasons:
        decision = PackageGateDecision.REVIEW_REQUIRED
    else:
        decision = PackageGateDecision.CLEARED

    cleared: tuple[SecurityClearedArtifact, ...] = ()
    if decision is PackageGateDecision.CLEARED:
        cleared = tuple(
            SecurityClearedArtifact(
                artifact=result.artifact,
                document_id=result.document_id,
                security_result=result,
            )
            for result in matched
        )

    return PackageGateResult(
        decision=decision,
        policy_id=MVP_GATE_POLICY_ID,
        document_results=document_results,
        cleared=cleared,
        reasons=tuple(reasons),
    )


def _finding_for(check: SecurityCheckResult) -> SecurityFinding:
    severity = check.severity or _FINDING_SEVERITY_FOR_STATUS.get(check.status, Severity.MEDIUM)
    return SecurityFinding(
        check=check.check,
        severity=severity,
        message=check.message,
        details=check.details,
    )
