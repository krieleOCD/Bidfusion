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

from dataclasses import dataclass
from pathlib import Path

from bidfusion.bid_intelligence.matching import (
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    RequirementLanguage,
    assess_requirements,
    load_claims_snapshot,
)
from bidfusion.golden_dataset.contracts import KnowledgeSourceLocator
from bidfusion.local_ui import artifacts
from bidfusion.local_ui.golden_service import capability_label
from bidfusion.local_ui.registry import RunRecord
from bidfusion.local_ui.viewmodels import source_label

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
class AssessmentRow:
    """One requirement with its normalization, candidate match, and review."""

    requirement_id: str
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
    human_review: str = HUMAN_REVIEW_LABEL
    candidate_note: str = CANDIDATE_ONLY_LABEL


@dataclass(frozen=True, slots=True)
class KnowledgeAssessmentView:
    """Everything the knowledge assessment page renders."""

    run_key: str
    package_name: str
    store_available: bool
    store_note: str
    claim_count: int
    rows: tuple[AssessmentRow, ...]
    labels: tuple[str, ...] = ASSESSMENT_LABELS
    review_banner: str = HUMAN_REVIEW_LABEL
    candidate_note: str = CANDIDATE_ONLY_LABEL

    @property
    def method_note(self) -> str:
        """The verbatim explanation of how these assessments are produced."""
        return _METHOD_NOTE.format(count=self.claim_count)


def build_knowledge_assessment_view(
    record: RunRecord,
    store_root: Path,
) -> KnowledgeAssessmentView | None:
    """Assessment page projection, or ``None`` when the run does not permit it.

    Only a processed run whose recorded outcome is ``completed`` may
    render this view — the same gate as the working package, so the page
    always stands on quality-accepted, integrity-verified artifacts.
    May raise :class:`bidfusion.local_ui.artifacts.ArtifactAccessError`
    when the run's integrity re-check fails.
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
    result = assess_requirements(requirements.requirements, snapshot)
    filenames = snapshot.source_filenames
    return KnowledgeAssessmentView(
        run_key=record.key,
        package_name=record.package_name,
        store_available=result.store_state is KnowledgeStoreState.AVAILABLE,
        store_note=result.store_note,
        claim_count=result.claim_count,
        rows=tuple(_row(item, filenames) for item in result.assessments),
    )


def _row(
    assessment: RequirementKnowledgeAssessment,
    filenames: dict[str, str],
) -> AssessmentRow:
    return AssessmentRow(
        requirement_id=assessment.requirement_id,
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
