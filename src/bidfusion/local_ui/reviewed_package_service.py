"""Generation and display of persisted Reviewed Working Packages.

Two narrow responsibilities, both server-authoritative:

- **Generate** — recompute the run's assessments from its
  integrity-verified artifacts and the current knowledge snapshot, load
  the run's review records, build the next package version through the
  deterministic builder, and persist it append-only. The POST carries no
  data; the client cannot submit review decisions, evidence, package
  versions, claim states, or requirement bodies.
- **Display** — load the latest persisted package fully verified and
  project it into path-free view structures. A package that fails its
  integrity verification is *never* rendered as valid; the page shows an
  explicit failure note instead.

Nothing here mutates the run, the review store, or any golden state,
and package state is always review *coverage* — never a compliance or
fulfilment claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bidfusion.bid_intelligence.matching import RequirementKnowledgeAssessment
from bidfusion.bid_intelligence.review import (
    PackageBuildError,
    PackageReviewState,
    PackageStoreConflictError,
    PackageStoreIntegrityError,
    RequirementAssessmentReview,
    ReviewedPackageRequirement,
    ReviewedPackageStore,
    ReviewedWorkingPackage,
    assessment_digest,
    build_reviewed_working_package,
    project_reviewed_assessments,
)
from bidfusion.local_ui.knowledge_assessment_service import (
    compute_assessment_inputs,
    load_reviews,
)
from bidfusion.local_ui.registry import RunRecord
from bidfusion.local_ui.viewmodels import source_label
from bidfusion.shared.identifiers import ArtifactIdAllocator

REVIEWED_PACKAGE_TITLE = "REVIEWED WORKING PACKAGE"

_STATE_LABELS: dict[PackageReviewState, str] = {
    PackageReviewState.REVIEW_COMPLETE: "REVIEW COMPLETE",
    PackageReviewState.REVIEW_INCOMPLETE: "REVIEW INCOMPLETE",
}

_PENDING_LABEL = "PENDING — no decision recorded"
_REVIEW_LABELS = {
    "CONFIRMED": "REVIEW CONFIRMED CANDIDATE",
    "REJECTED": "REVIEW REJECTED CANDIDATE",
    "NEEDS_CLARIFICATION": "CLARIFICATION REQUIRED",
}

_NOT_EVALUATED_LABEL = "NOT EVALUATED"

#: Static notes the package section shows verbatim.
PACKAGE_SCOPE_NOTE = (
    "Package state reports human-review coverage only. It is never a "
    "statement that any requirement is met."
)
PACKAGE_GOLDEN_NOTE = (
    "Golden claim states are recorded as found and remain unchanged by any "
    "bid review or package generation."
)
NEWER_REVIEWS_NOTE = (
    "A newer review state exists. Generate the next package version to "
    "capture it; this stored version stays unchanged."
)

_PACKAGES_BROKEN_NOTE = (
    "The stored reviewed packages for this run could not be validated. No "
    "package is shown and no new version is generated until they validate "
    "again."
)
_REVIEWS_BROKEN_NOTE = (
    "The stored review records for this run could not be read; no package "
    "is generated until they validate again."
)
_GENERATION_FAILED_NOTE = "The reviewed package could not be generated from the current run state."
_CONCURRENT_GENERATION_NOTE = (
    "Another reviewed package version was generated at the same moment. "
    "Reload the page to see the current package state."
)


class PackageGenerationError(RuntimeError):
    """Package generation was refused; the message is static and safe."""


def packages_root_for(record: RunRecord) -> Path:
    """Where this run's reviewed packages live: beside, never inside, the run.

    The run directory's integrity manifest is sealed at pipeline time,
    so reviewed packages are stored in a sibling directory under the
    run's private output root — the same convention as the review store.
    """
    return record.output_root / "reviewed-packages"


@dataclass(frozen=True, slots=True)
class PackageEvidenceView:
    """One golden evidence pointer of a package entry."""

    section_id: str
    source_version: str


@dataclass(frozen=True, slots=True)
class PackageRequirementRow:
    """One package entry with its three trust layers kept visibly apart."""

    requirement_id: str
    text: str
    modality: str
    source: str
    match_status: str
    claim_status: str
    evidence: tuple[PackageEvidenceView, ...]
    review_label: str
    reviewer: str | None
    reviewed_at: str | None
    review_version: int | None
    review_rationale: str | None


@dataclass(frozen=True, slots=True)
class ReviewedPackageView:
    """The latest persisted reviewed package, ready to render."""

    package_id: str
    package_version: int
    created_at: str
    state_label: str
    is_complete: bool
    total_requirements: int
    reviewed: int
    pending: int
    confirmed_candidate: int
    rejected_candidate: int
    needs_clarification: int
    rows: tuple[PackageRequirementRow, ...]
    newer_reviews_exist: bool
    newer_reviews_note: str = NEWER_REVIEWS_NOTE
    title: str = REVIEWED_PACKAGE_TITLE
    scope_note: str = PACKAGE_SCOPE_NOTE
    golden_note: str = PACKAGE_GOLDEN_NOTE


@dataclass(frozen=True, slots=True)
class ReviewedPackageSection:
    """Everything the working-package page needs about persisted packages."""

    package: ReviewedPackageView | None
    packages_available: bool
    packages_note: str | None
    can_generate: bool
    title: str = REVIEWED_PACKAGE_TITLE


def build_reviewed_package_section(
    record: RunRecord,
    store_root: Path,
) -> ReviewedPackageSection | None:
    """Section view for one permitted run, or ``None`` when not permitted.

    May raise :class:`bidfusion.local_ui.artifacts.ArtifactAccessError`
    when the run's integrity re-check fails.
    """
    inputs = compute_assessment_inputs(record, store_root)
    if inputs is None:
        return None
    try:
        latest = ReviewedPackageStore(packages_root_for(record)).read_latest()
    except (PackageStoreIntegrityError, OSError):
        return ReviewedPackageSection(
            package=None,
            packages_available=False,
            packages_note=_PACKAGES_BROKEN_NOTE,
            can_generate=False,
        )
    reviews = load_reviews(record)
    if latest is None:
        return ReviewedPackageSection(
            package=None,
            packages_available=True,
            packages_note=None,
            can_generate=reviews is not None,
        )
    _, result = inputs
    newer = _newer_review_state_exists(latest, result.assessments, reviews)
    return ReviewedPackageSection(
        package=_package_view(latest, newer_reviews_exist=newer),
        packages_available=True,
        packages_note=None,
        can_generate=reviews is not None and newer,
    )


def generate_reviewed_package(
    record: RunRecord,
    store_root: Path,
    *,
    now: datetime | None = None,
) -> ReviewedWorkingPackage | None:
    """Recompute everything server-side and persist the next package version.

    Returns ``None`` when the run does not permit assessment at all (the
    caller renders its usual not-found state). Raises
    :class:`PackageGenerationError` with a static message when the review
    store, the package store, or the build refuses. May raise
    :class:`bidfusion.local_ui.artifacts.ArtifactAccessError` when the
    run's integrity re-check fails — no package is ever generated for an
    integrity-invalid run.
    """
    inputs = compute_assessment_inputs(record, store_root)
    if inputs is None:
        return None
    requirements, result = inputs
    reviews = load_reviews(record)
    if reviews is None:
        raise PackageGenerationError(_REVIEWS_BROKEN_NOTE)
    store = ReviewedPackageStore(packages_root_for(record))
    try:
        version = store.next_version()
    except (PackageStoreIntegrityError, OSError) as failure:
        raise PackageGenerationError(_PACKAGES_BROKEN_NOTE) from failure
    created_at = now if now is not None else datetime.now(UTC)
    try:
        package = build_reviewed_working_package(
            requirements,
            assessments=result.assessments,
            reviews=reviews,
            package_version=version,
            artifact_id=ArtifactIdAllocator(created_at).allocate(),
            created_at=created_at,
        )
    except (PackageBuildError, ValueError) as failure:
        raise PackageGenerationError(_GENERATION_FAILED_NOTE) from failure
    try:
        store.append_package(package)
    except PackageStoreConflictError as failure:
        raise PackageGenerationError(_CONCURRENT_GENERATION_NOTE) from failure
    except (PackageStoreIntegrityError, OSError) as failure:
        raise PackageGenerationError(_PACKAGES_BROKEN_NOTE) from failure
    return package


def _newer_review_state_exists(
    latest: ReviewedWorkingPackage,
    assessments: tuple[RequirementKnowledgeAssessment, ...],
    reviews: tuple[RequirementAssessmentReview, ...] | None,
) -> bool:
    """Whether the current review state differs from the stored snapshot.

    Compares, per assessment digest, the latest *applicable* review
    binding of the current state with what the package captured. Any
    difference — a new review, a new revision, or a changed assessment
    set — means the stored package no longer reflects the present state.
    """
    projection = project_reviewed_assessments(assessments, reviews if reviews is not None else ())
    current = {
        assessment_digest(item.assessment): (
            None if item.review is None else (item.review.review_id, item.review.review_version)
        )
        for item in projection.reviewed
    }
    stored = {
        entry.machine.assessment_digest: (
            None
            if entry.human_review is None
            else (entry.human_review.review_id, entry.human_review.review_version)
        )
        for entry in latest.requirements
    }
    return current != stored


def _package_view(
    package: ReviewedWorkingPackage, *, newer_reviews_exist: bool
) -> ReviewedPackageView:
    return ReviewedPackageView(
        package_id=package.package_id,
        package_version=package.package_version,
        created_at=package.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        state_label=_STATE_LABELS[package.package_review_state],
        is_complete=package.package_review_state is PackageReviewState.REVIEW_COMPLETE,
        total_requirements=package.summary.total_requirements,
        reviewed=package.summary.reviewed,
        pending=package.summary.pending,
        confirmed_candidate=package.summary.confirmed_candidate,
        rejected_candidate=package.summary.rejected_candidate,
        needs_clarification=package.summary.needs_clarification,
        rows=tuple(_row(entry) for entry in package.requirements),
        newer_reviews_exist=newer_reviews_exist,
    )


def _row(entry: ReviewedPackageRequirement) -> PackageRequirementRow:
    review = entry.human_review
    return PackageRequirementRow(
        requirement_id=entry.rfp.requirement_id,
        text=entry.rfp.text,
        modality=entry.rfp.modality.value,
        source=source_label(entry.rfp.source),
        match_status=(
            entry.machine.match_status.value.replace("_", " ")
            if entry.machine.match_status is not None
            else _NOT_EVALUATED_LABEL
        ),
        claim_status=(
            entry.golden.claim_status.value.replace("_", " ")
            if entry.golden.claim_status is not None
            else "—"
        ),
        evidence=tuple(
            PackageEvidenceView(
                section_id=reference.section_id,
                source_version=reference.source_version or "—",
            )
            for reference in entry.golden.evidence_refs
        ),
        review_label=(_PENDING_LABEL if review is None else _REVIEW_LABELS[review.decision.value]),
        reviewer=None if review is None else review.reviewer,
        reviewed_at=(
            None
            if review is None
            else review.reviewed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        ),
        review_version=None if review is None else review.review_version,
        review_rationale=None if review is None else review.rationale,
    )
