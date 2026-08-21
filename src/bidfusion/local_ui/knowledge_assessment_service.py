"""View models for the requirement-to-golden-knowledge assessment page.

Pure projection: the assessment itself is computed by
:mod:`bidfusion.bid_intelligence.matching`; this module only loads the
run's recorded requirement artifacts, hands them to that service, and
turns the result into path-free display structures. No matching rule,
status decision, or store repair lives here.

Product honesty is carried in the view model, not the template: the RFP
side is always the repository's own synthetic fixture input, the golden
side is the local internal knowledge pilot, and every row states its
human-review requirement. A missing or damaged golden store renders as
an honest "not evaluated" state — never as a capability gap and never
as a traceback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

from bidfusion.bid_intelligence.matching import (
    KnowledgeAssessmentResult,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    RequirementLanguage,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.review import (
    RequirementAssessmentReview,
    ReviewedRequirementAssessment,
    ReviewState,
    RunReviewStore,
    assessment_digest,
    project_reviewed_assessments,
)
from bidfusion.golden_dataset.contracts import KnowledgeSourceLocator
from bidfusion.local_ui import artifacts
from bidfusion.local_ui.golden_service import capability_label
from bidfusion.local_ui.registry import RunRecord
from bidfusion.local_ui.viewmodels import source_label
from bidfusion.schemas.extraction import RequirementExtractionResult

#: Honest banner lines the assessment page shows verbatim.
ASSESSMENT_LABELS = (
    "SYNTHETIC RFP INPUT",
    "INTERNAL KNOWLEDGE PILOT",
    "LOCAL DATASET",
    "HUMAN REVIEW REQUIRED",
)

HUMAN_REVIEW_LABEL = "HUMAN REVIEW REQUIRED"
CANDIDATE_ONLY_LABEL = "Candidate match — not a compliance decision"
NOT_EVALUATED_LABEL = "NOT EVALUATED"
NEGATED_LANGUAGE_LABEL = "NEGATIVE OR EXCLUDING LANGUAGE"
OBLIGATION_LANGUAGE_LABEL = "OBLIGATION"

#: Scope statements every review control carries verbatim.
REVIEW_SCOPE_NOTE = "This decision applies to this bid assessment only."
REVIEW_GOLDEN_NOTE = "It does not validate or modify the underlying Golden Knowledge claim."

_REVIEWS_BROKEN_NOTE = (
    "The stored review records for this run could not be read. No review is "
    "shown or accepted until they validate again."
)

_REVIEW_STATE_LABELS: dict[ReviewState, str] = {
    ReviewState.PENDING: "PENDING — no decision recorded",
    ReviewState.CONFIRMED: "REVIEW CONFIRMED CANDIDATE",
    ReviewState.REJECTED: "REVIEW REJECTED CANDIDATE",
    ReviewState.NEEDS_CLARIFICATION: "CLARIFICATION REQUIRED",
}

#: Decision options the review form renders; values are the closed enum.
REVIEW_DECISION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("CONFIRMED", "Confirm candidate"),
    ("REJECTED", "Reject candidate"),
    ("NEEDS_CLARIFICATION", "Needs clarification"),
)

_METHOD_NOTE = (
    "The requirements below were extracted from this run's SYNTHETIC RFP "
    "fixture package by the deterministic rule-based pipeline. Each one is "
    "converted into a golden requirement candidate and matched by fixed "
    "capability keywords against {count} machine-extracted capability claims "
    "from the local golden knowledge store. Every claim is EXTRACTED "
    "UNVERIFIED and every result stays HUMAN REVIEW REQUIRED: a candidate "
    "match confirms nothing until a person reviews it. No embeddings, no "
    "vector database, no LLM, no network."
)


@dataclass(frozen=True, slots=True)
class AssessmentEvidenceView:
    """One golden evidence pointer: filename, section, version, locator."""

    filename: str
    section_id: str
    source_version: str
    locator: str


@dataclass(frozen=True, slots=True)
class ReviewStateView:
    """The human-review dimension of one assessment, ready to render."""

    label: str
    is_pending: bool
    reviewer: str | None = None
    reviewed_at: str | None = None
    review_rationale: str | None = None
    review_version: int | None = None


@dataclass(frozen=True, slots=True)
class AssessmentRow:
    """One requirement with its normalization, candidate match, and review."""

    requirement_id: str
    assessment_id: str
    assessment_digest: str
    requirement_text: str
    modality: str
    is_mandatory: bool
    source: str
    language: str
    technology_hint: str
    capability_hints: tuple[str, ...]
    match_status: str
    matched_capability: str
    claim_status: str
    rationale: str
    evidence: tuple[AssessmentEvidenceView, ...]
    review: ReviewStateView = field(
        default_factory=lambda: ReviewStateView(
            label=_REVIEW_STATE_LABELS[ReviewState.PENDING], is_pending=True
        )
    )
    human_review: str = HUMAN_REVIEW_LABEL
    candidate_note: str = CANDIDATE_ONLY_LABEL
    review_scope_note: str = REVIEW_SCOPE_NOTE
    review_golden_note: str = REVIEW_GOLDEN_NOTE


@dataclass(frozen=True, slots=True)
class ReviewCountsView:
    """How many assessments sit in each review state, for the summary."""

    pending: int
    confirmed: int
    rejected: int
    needs_clarification: int


@dataclass(frozen=True, slots=True)
class KnowledgeAssessmentView:
    """Everything the knowledge assessment page renders."""

    run_key: str
    package_name: str
    store_available: bool
    store_note: str
    claim_count: int
    rows: tuple[AssessmentRow, ...]
    reviews_available: bool = True
    reviews_note: str | None = None
    review_counts: ReviewCountsView = ReviewCountsView(0, 0, 0, 0)
    decision_options: tuple[tuple[str, str], ...] = REVIEW_DECISION_OPTIONS
    labels: tuple[str, ...] = ASSESSMENT_LABELS
    review_banner: str = HUMAN_REVIEW_LABEL
    candidate_note: str = CANDIDATE_ONLY_LABEL
    review_scope_note: str = REVIEW_SCOPE_NOTE
    review_golden_note: str = REVIEW_GOLDEN_NOTE

    @property
    def method_note(self) -> str:
        """The verbatim explanation of how these assessments are produced."""
        return _METHOD_NOTE.format(count=self.claim_count)


def compute_assessment_inputs(
    record: RunRecord,
    store_root: Path,
) -> tuple[RequirementExtractionResult, KnowledgeAssessmentResult] | None:
    """The run's authoritative requirements plus their assessment batch.

    Only a processed run whose recorded outcome is ``completed`` may be
    assessed — the same gate as the working package, so both the pages
    and every review-side mutation always stand on quality-accepted,
    integrity-verified artifacts. May raise
    :class:`bidfusion.local_ui.artifacts.ArtifactAccessError` when the
    run's integrity re-check fails.
    """
    summary = record.summary
    if (
        not record.requested_processing
        or summary.outcome != "completed"
        or "working_package_markdown" not in summary.outputs
    ):
        return None
    requirements = artifacts.load_requirements(summary.run_directory)
    snapshot = load_claims_snapshot(store_root)
    return requirements, assess_requirements(requirements.requirements, snapshot)


def compute_assessment_result(
    record: RunRecord,
    store_root: Path,
) -> KnowledgeAssessmentResult | None:
    """The deterministic assessment batch for one permitted run, or ``None``."""
    inputs = compute_assessment_inputs(record, store_root)
    return None if inputs is None else inputs[1]


def reviews_root_for(record: RunRecord) -> Path:
    """Where this run's review records live: beside, never inside, the run.

    The run directory's integrity manifest is sealed at pipeline time,
    so review records are stored in a sibling directory under the run's
    private output root.
    """
    return record.output_root / "reviews"


def load_reviews(record: RunRecord) -> tuple[RequirementAssessmentReview, ...] | None:
    """Stored reviews for one run; ``None`` means the store is damaged."""
    try:
        return RunReviewStore(reviews_root_for(record)).read_reviews()
    except Exception:  # noqa: BLE001 - a broken review store must never raise into a page
        return None


def build_knowledge_assessment_view(
    record: RunRecord,
    store_root: Path,
) -> KnowledgeAssessmentView | None:
    """Assessment page projection, or ``None`` when the run does not permit it."""
    result = compute_assessment_result(record, store_root)
    if result is None:
        return None
    snapshot = load_claims_snapshot(store_root)
    filenames = snapshot.source_filenames
    reviews = load_reviews(record)
    projection = project_reviewed_assessments(
        result.assessments, reviews if reviews is not None else ()
    )
    counts = projection.counts
    reviewed_by_id = {item.assessment.assessment_id: item for item in projection.reviewed}
    return KnowledgeAssessmentView(
        run_key=record.key,
        package_name=record.package_name,
        store_available=result.store_state is KnowledgeStoreState.AVAILABLE,
        store_note=result.store_note,
        claim_count=result.claim_count,
        rows=tuple(
            _row(
                item,
                filenames,
                review_view=_review_state_view(reviewed_by_id[item.assessment_id]),
            )
            for item in result.assessments
        ),
        reviews_available=reviews is not None,
        reviews_note=None if reviews is not None else _REVIEWS_BROKEN_NOTE,
        review_counts=ReviewCountsView(
            pending=counts[ReviewState.PENDING],
            confirmed=counts[ReviewState.CONFIRMED],
            rejected=counts[ReviewState.REJECTED],
            needs_clarification=counts[ReviewState.NEEDS_CLARIFICATION],
        ),
    )


def build_review_summary(
    record: RunRecord,
    store_root: Path,
) -> KnowledgeAssessmentView | None:
    """The reviewed working-package projection for the working-package page.

    Same data as the assessment page — machine candidate, golden claim
    state, and human review stay three distinct concepts — reused so the
    working package never grows its own matching or review logic.
    """
    return build_knowledge_assessment_view(record, store_root)


def _review_state_view(reviewed: ReviewedRequirementAssessment) -> ReviewStateView:
    review = reviewed.review
    if review is None:
        return ReviewStateView(label=_REVIEW_STATE_LABELS[ReviewState.PENDING], is_pending=True)
    return ReviewStateView(
        label=_REVIEW_STATE_LABELS[reviewed.review_state],
        is_pending=False,
        reviewer=review.reviewer,
        reviewed_at=review.reviewed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        review_rationale=review.rationale,
        review_version=review.review_version,
    )


def _row(
    assessment: RequirementKnowledgeAssessment,
    filenames: dict[str, str],
    *,
    review_view: ReviewStateView,
) -> AssessmentRow:
    return AssessmentRow(
        requirement_id=assessment.requirement_id,
        assessment_id=assessment.assessment_id,
        assessment_digest=assessment_digest(assessment),
        review=review_view,
        requirement_text=assessment.requirement_text,
        modality=assessment.requirement_modality.value,
        is_mandatory=assessment.mandatory,
        source=source_label(assessment.requirement_source),
        language=(
            NEGATED_LANGUAGE_LABEL
            if assessment.requirement_language is RequirementLanguage.NEGATED_OR_EXCLUDED
            else OBLIGATION_LANGUAGE_LABEL
        ),
        technology_hint=assessment.technology_hint.value.replace("_", " "),
        capability_hints=tuple(
            capability_label(capability) for capability in assessment.capability_hints
        ),
        match_status=(
            assessment.match_status.value.replace("_", " ")
            if assessment.match_status is not None
            else NOT_EVALUATED_LABEL
        ),
        matched_capability=(
            capability_label(assessment.matched_capability)
            if assessment.matched_capability is not None
            else "—"
        ),
        claim_status=(
            assessment.knowledge_claim_status.value.replace("_", " ")
            if assessment.knowledge_claim_status is not None
            else "—"
        ),
        rationale=assessment.rationale,
        evidence=tuple(
            AssessmentEvidenceView(
                filename=filenames.get(reference.source_id, "unknown source"),
                section_id=reference.section_id,
                source_version=reference.source_version or "—",
                locator=_locator_label(reference.locator),
            )
            for reference in assessment.evidence_refs
        ),
    )


def _locator_label(locator: KnowledgeSourceLocator) -> str:
    """Short human-readable location inside one golden source."""
    if locator.page is not None:
        return f"page {locator.page}"
    if locator.paragraph_index is not None:
        return f"paragraph {locator.paragraph_index}"
    if locator.heading is not None:
        return f"heading {locator.heading}"
    if locator.sheet is not None and locator.cell_range is not None:
        return f"sheet {locator.sheet} ({locator.cell_range})"
    if locator.sheet is not None:
        return f"sheet {locator.sheet}"
    if locator.table is not None:
        return f"table {locator.table}"
    if locator.line_start is not None:
        end = locator.line_end if locator.line_end is not None else locator.line_start
        return f"lines {locator.line_start}-{end}"
    return "whole document"
