"""Frozen Evaluation #3 of real-RFP requirement extraction, as UI data.

A hand-transcribed copy of the frozen evaluation record (extractor
0.3.0 against the curated 364-requirement Ground Truth of the real
8-document tender package). Static configuration in the same spirit as
the feature registry: no I/O, no paths, no pipeline imports. When a
runtime evaluation source exists, it replaces :data:`EVALUATION`; the
view model and template stay as they are.

Honesty rules of this record:

- unmapped candidates are never presented as proven false requirements;
- every figure is a measurement of extractor coverage, not a statement
  about the tender documents themselves;
- nothing here claims completeness or production readiness.
"""

from __future__ import annotations

from dataclasses import dataclass

EVALUATION_STATUS_FROZEN = "FROZEN"


@dataclass(frozen=True, slots=True)
class MatchCounts:
    """How the Ground Truth requirements mapped to candidates."""

    exact: int
    partial: int
    ambiguous: int
    missed: int
    unmapped_candidates: int
    duplicate_extractions: int


@dataclass(frozen=True, slots=True)
class RecallMetrics:
    """The two frozen recall figures, in percent."""

    strict_percent: float
    inclusive_percent: float


@dataclass(frozen=True, slots=True)
class Milestone:
    """One recall milestone and whether the frozen result reached it."""

    label: str
    threshold_label: str
    reached: bool


@dataclass(frozen=True, slots=True)
class PilotReadiness:
    """Readiness verdict for the next controlled pilot."""

    pilot_label: str
    verdict_label: str
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    """One measured step of the development loop."""

    version: str
    candidates: int
    strict_percent: float
    inclusive_percent: float
    added: str


@dataclass(frozen=True, slots=True)
class DocumentCoverage:
    """Extractor coverage of one RFP document's Ground Truth entries."""

    name: str
    ground_truth: int
    missed: int
    band: str
    """``strong``, ``mid``, or ``weak`` — extractor coverage, never
    a judgement about the document."""


@dataclass(frozen=True, slots=True)
class GapCategory:
    """One false-negative class of the remaining misses."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class RuleSignal:
    """One detection rule family and how cleanly it performed."""

    label: str
    matched: int
    outputs: int
    band: str
    """``high-precision``, ``useful``, or ``needs-refinement``."""


@dataclass(frozen=True, slots=True)
class NextStep:
    """The single recommended next engineering step."""

    title: str
    description: str
    reason: str
    after: str


@dataclass(frozen=True, slots=True)
class RealRfpExtractionEvaluation:
    """The complete frozen evaluation record this page presents."""

    evaluation_id: str
    extractor_version: str
    source_label: str
    evaluation_status: str
    context: str
    ground_truth_count: int
    candidate_count: int
    matches: MatchCounts
    recall: RecallMetrics
    milestones: tuple[Milestone, ...]
    pilot: PilotReadiness
    history: tuple[HistoryPoint, ...]
    documents: tuple[DocumentCoverage, ...]
    gaps: tuple[GapCategory, ...]
    levers: tuple[str, ...]
    rules: tuple[RuleSignal, ...]
    next_step: NextStep
    unmapped_note: str


EVALUATION = RealRfpExtractionEvaluation(
    evaluation_id="requirement-extraction-evaluation-3",
    extractor_version="0.3.0",
    source_label="Frozen Evaluation #3",
    evaluation_status=EVALUATION_STATUS_FROZEN,
    context=(
        "Evaluation against 364 manually curated requirements from an "
        "8-document real tender package. Deterministic extraction only — "
        "no model call anywhere in this measurement."
    ),
    ground_truth_count=364,
    candidate_count=230,
    matches=MatchCounts(
        exact=245,
        partial=31,
        ambiguous=16,
        missed=72,
        unmapped_candidates=71,
        duplicate_extractions=0,
    ),
    recall=RecallMetrics(strict_percent=67.3, inclusive_percent=75.8),
    milestones=(
        Milestone(label="Milestone A", threshold_label="70% inclusive recall", reached=True),
        Milestone(label="Milestone B", threshold_label="85% inclusive recall", reached=False),
        Milestone(label="Stretch", threshold_label="95% inclusive recall", reached=False),
    ),
    pilot=PilotReadiness(
        pilot_label="Controlled Real RFP Pilot #2",
        verdict_label="Ready with conditions",
        conditions=(
            "The extractor changes behind this result still require review and a recorded commit.",
            "151 Ground Truth requirements are represented inside over-merged candidate blocks.",
            "Procedure-statement detection remains noisy and needs refinement.",
        ),
    ),
    history=(
        HistoryPoint("v0.1", 0, 0.0, 0.0, "Explicit labels only"),
        HistoryPoint("v0.2", 88, 15.4, 18.4, "First label-free rule families"),
        HistoryPoint("v0.3a", 120, 23.4, 28.3, "Contractor obligations"),
        HistoryPoint("v0.3b", 136, 24.7, 30.2, "Plain modal statements"),
        HistoryPoint("v0.3c", 170, 46.4, 54.7, "Bulleted service items"),
        HistoryPoint("v0.3d", 188, 51.1, 59.3, "Priced positions, spreadsheet"),
        HistoryPoint("v0.3e", 195, 53.3, 63.5, "Priced positions, flattened tables"),
        HistoryPoint("v0.3f", 204, 54.1, 64.3, "Exclusion formalities"),
        HistoryPoint("v0.3g", 185, 61.5, 69.0, "Longer clause assembly"),
        HistoryPoint("v0.3h", 230, 67.3, 75.8, "Procedure statements"),
    ),
    documents=(
        DocumentCoverage("Leistungsbeschreibung", 172, 9, "strong"),
        DocumentCoverage("Preiserhebungsblatt XLSX", 19, 1, "strong"),
        DocumentCoverage("Kriterienkatalog", 28, 8, "mid"),
        DocumentCoverage("Vertragsstrafe", 4, 1, "mid"),
        DocumentCoverage("Angebotsbedingungen", 51, 11, "mid"),
        DocumentCoverage("Bedingungen Teilnahmewettbewerb", 30, 16, "weak"),
        DocumentCoverage("Formulare", 25, 11, "weak"),
        DocumentCoverage("Vertrag", 35, 15, "weak"),
    ),
    gaps=(
        GapCategory("Implicit normative language", 18),
        GapCategory("Mandatory documents", 13),
        GapCategory("Form fields", 9),
        GapCategory("Criterion structure", 7),
        GapCategory("Quantity and thresholds", 7),
        GapCategory("Table structure", 6),
        GapCategory("Deadlines", 5),
        GapCategory("Parser and structure loss", 3),
        GapCategory("Cross-sentence context", 2),
        GapCategory("Other", 2),
    ),
    levers=(
        "Contract mechanics and implicit obligations",
        "Mandatory-document recognition",
        "Form and field structure",
    ),
    rules=(
        RuleSignal("List service items", 23, 23, "high-precision"),
        RuleSignal("Priced positions", 22, 22, "high-precision"),
        RuleSignal("Criterion and question", 28, 34, "useful"),
        RuleSignal("Contractual obligation", 27, 38, "useful"),
        RuleSignal("Numbered modal", 26, 35, "useful"),
        RuleSignal("Procedure statements", 15, 40, "needs-refinement"),
        RuleSignal("Modal statements", 4, 14, "needs-refinement"),
    ),
    next_step=NextStep(
        title="Atomic Requirement Splitting",
        description=(
            "Split compound requirement blocks and bullet groups into atomic "
            "per-requirement candidates."
        ),
        reason=(
            "151 Ground Truth requirements are currently represented inside "
            "over-merged candidates. This is the largest measured quality gap "
            "and should improve strict recall and Pilot #2 input quality "
            "without requiring new detection machinery."
        ),
        after="deterministic extractor and LLM challenger, compared on the same package",
    ),
    unmapped_note=(
        "Candidates without a Ground Truth mapping; some may represent "
        "genuine requirements outside the curated Ground Truth."
    ),
)


# --- view model ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """One progression row with a whole-percent bar the CSS can consume."""

    version: str
    candidates: int
    strict_label: str
    inclusive_label: str
    inclusive_bar_percent: int
    added: str
    is_current: bool


@dataclass(frozen=True, slots=True)
class DocumentRow:
    """One document-coverage row with precomputed display values."""

    name: str
    ground_truth: int
    missed: int
    covered: int
    coverage_percent: int
    band: str
    band_label: str


@dataclass(frozen=True, slots=True)
class GapRow:
    """One gap category with a bar scaled to the largest category."""

    label: str
    count: int
    bar_percent: int


@dataclass(frozen=True, slots=True)
class RuleRow:
    """One rule family with its quality band label."""

    label: str
    matched: int
    outputs: int
    band: str
    band_label: str


@dataclass(frozen=True, slots=True)
class ExtractionQualityPageView:
    """Everything the extraction-quality template renders."""

    evaluation: RealRfpExtractionEvaluation
    strict_bar_percent: int
    inclusive_bar_percent: int
    history_rows: tuple[HistoryRow, ...]
    document_rows: tuple[DocumentRow, ...]
    gap_rows: tuple[GapRow, ...]
    rule_rows: tuple[RuleRow, ...]


_BAND_LABELS = {
    "strong": "Strong coverage",
    "mid": "Partial coverage",
    "weak": "Weakest coverage",
}

_RULE_BAND_LABELS = {
    "high-precision": "High precision signal",
    "useful": "Useful signal",
    "needs-refinement": "Needs refinement",
}


def _percent(numerator: int, denominator: int) -> int:
    return round(numerator * 100 / denominator) if denominator else 0


def build_page_view() -> ExtractionQualityPageView:
    """Project the frozen record into ready-to-render display rows."""
    record = EVALUATION
    history_rows = tuple(
        HistoryRow(
            version=point.version,
            candidates=point.candidates,
            strict_label=f"{point.strict_percent:.1f}%",
            inclusive_label=f"{point.inclusive_percent:.1f}%",
            inclusive_bar_percent=round(point.inclusive_percent),
            added=point.added,
            is_current=point is record.history[-1],
        )
        for point in record.history
    )
    document_rows = tuple(
        DocumentRow(
            name=item.name,
            ground_truth=item.ground_truth,
            missed=item.missed,
            covered=item.ground_truth - item.missed,
            coverage_percent=_percent(item.ground_truth - item.missed, item.ground_truth),
            band=item.band,
            band_label=_BAND_LABELS[item.band],
        )
        for item in record.documents
    )
    largest_gap = max(item.count for item in record.gaps)
    gap_rows = tuple(
        GapRow(
            label=item.label,
            count=item.count,
            bar_percent=_percent(item.count, largest_gap),
        )
        for item in record.gaps
    )
    rule_rows = tuple(
        RuleRow(
            label=item.label,
            matched=item.matched,
            outputs=item.outputs,
            band=item.band,
            band_label=_RULE_BAND_LABELS[item.band],
        )
        for item in record.rules
    )
    return ExtractionQualityPageView(
        evaluation=record,
        strict_bar_percent=round(record.recall.strict_percent),
        inclusive_bar_percent=round(record.recall.inclusive_percent),
        history_rows=history_rows,
        document_rows=document_rows,
        gap_rows=gap_rows,
        rule_rows=rule_rows,
    )


@dataclass(frozen=True, slots=True)
class SummaryCard:
    """The compact overview-card projection of the frozen result."""

    inclusive_label: str
    ground_truth_count: int
    candidate_count: int
    milestone_label: str
    source_label: str


def summary_card() -> SummaryCard:
    """The overview page's compact summary of the frozen evaluation."""
    reached = tuple(item for item in EVALUATION.milestones if item.reached)
    milestone_label = f"{reached[-1].label} reached" if reached else "No milestone reached"
    return SummaryCard(
        inclusive_label=f"{EVALUATION.recall.inclusive_percent:.1f}%",
        ground_truth_count=EVALUATION.ground_truth_count,
        candidate_count=EVALUATION.candidate_count,
        milestone_label=milestone_label,
        source_label=EVALUATION.source_label,
    )
