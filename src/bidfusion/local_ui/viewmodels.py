"""View models: pure projection of pipeline results into display structures.

The single source of truth is the pipeline output (run summaries and
versioned artifacts on disk). Nothing here decides gates or quality —
this module only projects the recorded decisions and enforces, in one
place, which sections a given outcome may render.
"""

from __future__ import annotations

from dataclasses import dataclass

from bidfusion.local_ui import artifacts
from bidfusion.local_ui.registry import RunRecord
from bidfusion.schemas.provenance import SourceReference
from bidfusion.schemas.working_package import EvidencedStatement

_GATE_DISPLAY = {
    "CLEARED": ("success", "check"),
    "REVIEW_REQUIRED": ("warning", "alert"),
    "BLOCKED": ("danger", "octagon-x"),
}

_VERDICT_DISPLAY = {
    "ALLOW": ("success", "check"),
    "BLOCK": ("danger", "x"),
    "MANUAL_REVIEW": ("warning", "alert"),
    "QUARANTINE": ("danger", "alert"),
}

_STAGE_OUTCOME_DISPLAY = {
    "SUCCEEDED": ("success", "check"),
    "REVIEW_REQUIRED": ("warning", "alert"),
    "FAILED": ("danger", "x"),
    "NOT_ATTEMPTED": ("neutral", "minus"),
}

_QUALITY_DISPLAY = {
    "ACCEPTABLE": ("success", "check"),
    "REVIEW_REQUIRED": ("warning", "alert"),
    "FAILED": ("danger", "x"),
}

_STAGE_LABELS = (
    ("intake", "Intake"),
    ("preflight", "Preflight"),
    ("package_gate", "Package gate"),
    ("parsing", "Parsing"),
    ("extraction", "Extraction"),
    ("normalization", "Normalization"),
    ("quality_gate", "Quality gate"),
    ("working_package", "Package generation"),
)


@dataclass(frozen=True, slots=True)
class StatusDisplay:
    """One status as label plus non-color signals (icon + text)."""

    label: str
    tone: str
    icon: str


@dataclass(frozen=True, slots=True)
class DocumentRow:
    """Security verdict of one registered document."""

    filename: str
    verdict: StatusDisplay
    detail: str | None


@dataclass(frozen=True, slots=True)
class GateView:
    """The package gate decision exactly as recorded by the pipeline."""

    policy_id: str
    decision: StatusDisplay
    reasons: tuple[str, ...]
    documents: tuple[DocumentRow, ...]
    rejected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StageRow:
    """One recorded pipeline stage and its contract outcome."""

    label: str
    outcome: StatusDisplay


@dataclass(frozen=True, slots=True)
class QualityView:
    """The quality gate result exactly as recorded by the pipeline."""

    gate_id: str
    status: StatusDisplay
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricTile:
    """One counted fact about a run, taken from what the run recorded."""

    label: str
    value: str
    tone: str
    note: str


@dataclass(frozen=True, slots=True)
class RunView:
    """Display projection of one recorded pipeline run."""

    key: str
    package_name: str
    requested_processing: bool
    outcome: str
    run_directory: str
    gate: GateView
    metrics: tuple[MetricTile, ...]
    stages: tuple[StageRow, ...]
    quality: QualityView | None
    offer_full_analysis: bool
    is_blocked: bool
    is_security_review: bool
    is_completed: bool
    is_quality_review: bool
    is_failed: bool


@dataclass(frozen=True, slots=True)
class StatementRow:
    """One evidence-bearing statement with human-readable source labels."""

    text: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequirementRow:
    """One normalized requirement for the scannable requirements tables."""

    requirement_id: str
    modality: str
    category: str
    text: str
    source: str


@dataclass(frozen=True, slots=True)
class TimelineRow:
    """One extracted deadline with provenance."""

    due: str
    kind: str
    description: str
    source: str


@dataclass(frozen=True, slots=True)
class OpenQuestionRow:
    """One open question raised by the pipeline."""

    question_id: str
    reason: str
    statement: StatementRow


@dataclass(frozen=True, slots=True)
class DownloadLink:
    """One allowlisted artifact offered for download."""

    name: str
    label: str


@dataclass(frozen=True, slots=True)
class WorkingPackageView:
    """Structured working-package view, built from validated artifacts."""

    bid_id: str
    run_id: str
    generated_at: str
    completeness: str
    total_requirements: int
    mandatory_count: int
    by_modality: tuple[tuple[str, int], ...]
    by_category: tuple[tuple[str, int], ...]
    executive: tuple[tuple[str, StatementRow], ...]
    timeline: tuple[TimelineRow, ...]
    mandatory: tuple[RequirementRow, ...]
    other: tuple[RequirementRow, ...]
    submissions: tuple[tuple[str, tuple[StatementRow, ...]], ...]
    open_questions: tuple[OpenQuestionRow, ...]
    downloads: tuple[DownloadLink, ...]


@dataclass(frozen=True, slots=True)
class ReviewPackageView:
    """Structured review-package view; never mistakable for a working package."""

    notice: str
    gate_id: str
    bid_id: str
    run_id: str
    generated_at: str
    reasons: tuple[str, ...]
    manual_actions: tuple[str, ...]
    warnings: tuple[str, ...]
    affected: tuple[str, ...]
    detected: tuple[tuple[str, tuple[StatementRow, ...]], ...]
    unresolved_conflicts: tuple[str, ...]
    downloads: tuple[DownloadLink, ...]


def status_display(label: str, mapping: dict[str, tuple[str, str]]) -> StatusDisplay:
    tone, icon_name = mapping.get(label, ("neutral", "minus"))
    return StatusDisplay(label=label, tone=tone, icon=icon_name)


def source_label(source: SourceReference) -> str:
    """Human-readable provenance label: document, page, or sheet cell."""
    locator = source.locator
    if locator.cell_id is not None:
        return f"{source.filename} ({locator.cell_id})"
    if locator.page is not None:
        return f"{source.filename} (p. {locator.page})"
    return source.filename


def build_run_view(record: RunRecord) -> RunView:
    """Project one run record; sections derive only from recorded status."""
    summary = record.summary
    decision = summary.gate.decision.value
    documents = tuple(
        DocumentRow(
            filename=state.filename,
            verdict=(
                status_display(state.verdict, _VERDICT_DISPLAY)
                if state.verdict is not None
                else StatusDisplay(label="UNASSESSED", tone="neutral", icon="minus")
            ),
            detail=state.assessment_error,
        )
        for state in summary.documents
    )
    gate = GateView(
        policy_id=summary.gate.policy_id,
        decision=status_display(decision, _GATE_DISPLAY),
        reasons=tuple(summary.gate.reasons),
        documents=documents,
        rejected=tuple(f"{rejected.filename}: {rejected.reason}" for rejected in summary.rejected),
    )
    stages = (
        tuple(
            StageRow(
                label=label,
                outcome=status_display(
                    str(summary.stages[name]["outcome"]), _STAGE_OUTCOME_DISPLAY
                ),
            )
            for name, label in _STAGE_LABELS
        )
        if record.requested_processing
        else ()
    )
    quality = (
        QualityView(
            gate_id=f"{summary.quality.gate_name}:{summary.quality.gate_version}",
            status=status_display(summary.quality.status.value, _QUALITY_DISPLAY),
            signals=tuple(signal.message for signal in summary.quality.signals),
        )
        if summary.quality is not None
        else None
    )
    return RunView(
        key=record.key,
        package_name=record.package_name,
        requested_processing=record.requested_processing,
        outcome=summary.outcome,
        run_directory=str(summary.run_directory),
        gate=gate,
        metrics=_run_metrics(documents, gate.rejected, quality),
        stages=stages,
        quality=quality,
        offer_full_analysis=(
            not record.requested_processing
            and summary.outcome == "security-only"
            and decision == "CLEARED"
        ),
        is_blocked=decision == "BLOCKED",
        is_security_review=decision == "REVIEW_REQUIRED",
        is_completed=summary.outcome == "completed",
        is_quality_review=summary.outcome == "review-required" and summary.quality is not None,
        is_failed=summary.outcome == "failed",
    )


def _run_metrics(
    documents: tuple[DocumentRow, ...],
    rejected: tuple[str, ...],
    quality: QualityView | None,
) -> tuple[MetricTile, ...]:
    """Counted facts about one run — every number is one the run recorded.

    Nothing here is estimated, projected, or filled in when a stage did
    not run: a count only appears once the run actually produced it.
    """
    verdicts = [row.verdict.label for row in documents]
    cleared = verdicts.count("ALLOW")
    manual = verdicts.count("MANUAL_REVIEW")
    blocked = verdicts.count("BLOCK") + verdicts.count("QUARANTINE")
    tiles = [
        MetricTile(
            label="Documents inventoried",
            value=str(len(documents)),
            tone="neutral",
            note="Registered at intake",
        ),
        MetricTile(
            label="Security verdict: allow",
            value=str(cleared),
            tone="success" if cleared else "neutral",
            note="Passed the deterministic preflight",
        ),
        MetricTile(
            label="Manual review",
            value=str(manual),
            tone="warning" if manual else "neutral",
            note="Pending a human security decision",
        ),
        MetricTile(
            label="Blocked",
            value=str(blocked),
            tone="danger" if blocked else "neutral",
            note="Never reached a parser",
        ),
        MetricTile(
            label="Rejected at intake",
            value=str(len(rejected)),
            tone="warning" if rejected else "neutral",
            note="Refused before assessment",
        ),
    ]
    if quality is not None:
        tiles.append(
            MetricTile(
                label="Quality signals",
                value=str(len(quality.signals)),
                tone="warning" if quality.signals else "success",
                note="Raised by the quality gate",
            )
        )
    return tuple(tiles)


_COMMON_DOWNLOADS = (
    DownloadLink(name="run-summary.json", label="Run summary (JSON)"),
    DownloadLink(name="quality-gate.json", label="Quality gate (JSON)"),
    DownloadLink(name="package-gate.json", label="Package gate (JSON)"),
)


def build_working_package_view(record: RunRecord) -> WorkingPackageView | None:
    """Structured working-package projection, or ``None`` when not permitted.

    Only a processed run whose recorded outcome is ``completed`` with an
    ``ACCEPTABLE`` quality gate and recorded working-package outputs may
    render this view; everything else yields ``None``.
    """
    summary = record.summary
    if (
        not record.requested_processing
        or summary.outcome != "completed"
        or summary.quality is None
        or summary.quality.status.value != "ACCEPTABLE"
        or "working_package_markdown" not in summary.outputs
    ):
        return None
    package, requirements, dataset = artifacts.load_working_package(summary.run_directory)

    requirements_by_id = {item.requirement_id: item for item in requirements.requirements}
    rows = []
    for reference in dataset.requirements:
        requirement = requirements_by_id.get(reference.object_id)
        if requirement is None:
            continue
        rows.append(
            RequirementRow(
                requirement_id=requirement.requirement_id,
                modality=requirement.modality.value,
                category=requirement.category.value,
                text=requirement.normalized_text or requirement.original_text,
                source=source_label(requirement.source),
            )
        )
    executive = tuple(
        (label, _statement_row(statement))
        for label, statements in (
            ("Customer", _optional(package.executive_overview.customer)),
            ("RFP title", _optional(package.executive_overview.rfp_title)),
            ("Opportunity", _optional(package.executive_overview.opportunity)),
            ("Scope", package.executive_overview.scope_summary),
            ("Objectives", package.executive_overview.objectives),
        )
        for statement in statements
    )
    instructions = package.submission_instructions
    submissions = tuple(
        (label, tuple(_statement_row(statement) for statement in statements))
        for label, statements in (
            ("Portal", _optional(instructions.portal)),
            ("Submission process", instructions.upload_process),
            ("Required accounts", instructions.required_accounts),
            ("Required formats", instructions.formats),
            ("Naming rules", instructions.naming_rules),
            ("Signatures", instructions.signatures_required),
            ("File size limits", instructions.file_size_limits),
            ("Special requirements", instructions.special_requirements),
        )
        if statements
    )
    completeness = dataset.completeness
    return WorkingPackageView(
        bid_id=str(package.bid_id),
        run_id=str(package.artifact.run_id),
        generated_at=package.generated_at.isoformat(),
        completeness=(
            f"{completeness.state.value} "
            f"({len(completeness.completed_streams)}/"
            f"{len(completeness.expected_streams)} streams completed)"
        ),
        total_requirements=package.requirements_summary.total,
        mandatory_count=len(package.critical_requirements),
        by_modality=tuple(
            (modality.value, count)
            for modality, count in sorted(
                package.requirements_summary.by_modality.items(),
                key=lambda entry: entry[0].value,
            )
        ),
        by_category=tuple(
            (category.value, count)
            for category, count in sorted(
                package.requirements_summary.by_category.items(),
                key=lambda entry: entry[0].value,
            )
        ),
        executive=executive,
        timeline=tuple(
            TimelineRow(
                due=deadline.due_at.strftime("%Y-%m-%d %H:%M UTC"),
                kind=deadline.kind.value,
                description=deadline.description or "—",
                source=source_label(deadline.source),
            )
            for deadline in package.timeline
        ),
        mandatory=tuple(row for row in rows if row.modality == "MUST"),
        other=tuple(row for row in rows if row.modality != "MUST"),
        submissions=submissions,
        open_questions=tuple(
            OpenQuestionRow(
                question_id=question.question_id,
                reason=question.reason,
                statement=_statement_row(question.statement),
            )
            for question in package.open_questions
        ),
        downloads=(
            DownloadLink(name="working-package.json", label="Working package (JSON)"),
            DownloadLink(name="working-package.md", label="Working package (Markdown)"),
            *_COMMON_DOWNLOADS,
        ),
    )


def build_review_package_view(record: RunRecord) -> ReviewPackageView | None:
    """Structured review-package projection, or ``None`` when not permitted.

    Only a processed run whose recorded outcome is ``review-required``
    with a quality gate report and recorded review-package outputs may
    render this view.
    """
    summary = record.summary
    if (
        not record.requested_processing
        or summary.outcome != "review-required"
        or summary.quality is None
        or "review_package_json" not in summary.outputs
    ):
        return None
    package = artifacts.load_review_package(summary.run_directory)
    return ReviewPackageView(
        notice=package.notice,
        gate_id=f"{package.quality_gate_name}:{package.quality_gate_version}",
        bid_id=str(package.bid_id),
        run_id=str(package.run_id),
        generated_at=package.generated_at.isoformat(),
        reasons=package.reasons,
        manual_actions=package.required_manual_actions,
        warnings=package.warnings,
        affected=(*package.affected_documents, *package.affected_sources),
        detected=(
            (
                "Detected requirements (partial)",
                tuple(
                    StatementRow(text=item.text, sources=item.sources)
                    for item in package.detected_requirements
                ),
            ),
            (
                "Detected deadlines (partial)",
                tuple(
                    StatementRow(text=item.text, sources=item.sources)
                    for item in package.detected_deadlines
                ),
            ),
            (
                "Detected formalities (partial)",
                tuple(
                    StatementRow(text=item.text, sources=item.sources)
                    for item in package.detected_formalities
                ),
            ),
        ),
        unresolved_conflicts=package.unresolved_conflicts,
        downloads=(
            DownloadLink(name="review-package.json", label="Review package (JSON)"),
            DownloadLink(name="review-package.md", label="Review package (Markdown)"),
            *_COMMON_DOWNLOADS,
        ),
    )


def _statement_row(statement: EvidencedStatement) -> StatementRow:
    return StatementRow(
        text=statement.text,
        sources=tuple(source_label(source) for source in statement.sources),
    )


def _optional(statement: EvidencedStatement | None) -> tuple[EvidencedStatement, ...]:
    return (statement,) if statement is not None else ()
