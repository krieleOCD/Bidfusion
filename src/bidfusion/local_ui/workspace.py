"""One run as a bid workspace: the workflow stepper and its key counts.

Pure presentation over already-built view models. This module decides
how far along the recorded workflow a run is and which counted facts
the bid overview shows — it never computes a match, a review, or a
package of its own, and every number is taken from a projection that a
service already produced from verified artifacts.

A completed technical step is presented as exactly that: workflow
progress, never business approval. The reviewed working package's own
state label (REVIEW INCOMPLETE / REVIEW COMPLETE) always travels with
the step that mentions it.
"""

from __future__ import annotations

from dataclasses import dataclass

from bidfusion.local_ui.knowledge_assessment_service import AssessmentRow, KnowledgeAssessmentView
from bidfusion.local_ui.reviewed_package_service import ReviewedPackageSection
from bidfusion.local_ui.viewmodels import RunView

#: Step states, in the only vocabulary the stepper knows. Each state is
#: always rendered as words as well as a color.
STATE_COMPLETE = "complete"
STATE_ACTIVE = "active"
STATE_PENDING = "pending"
STATE_ATTENTION = "attention"

_STATE_LABELS = {
    STATE_COMPLETE: "COMPLETE",
    STATE_ACTIVE: "ACTIVE",
    STATE_PENDING: "PENDING",
    STATE_ATTENTION: "ATTENTION",
}

#: Machine verdicts that name a candidate. Everything else (UNKNOWN,
#: GAP, NOT EVALUATED) is counted as "no candidate" — never hidden,
#: just not presented as a match.
_CANDIDATE_STATUSES = frozenset({"MATCHED", "PARTIAL"})


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One step of the bid workflow, with its state in words."""

    key: str
    label: str
    state: str
    state_label: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceCount:
    """One counted fact for the bid overview. Counted, never estimated."""

    label: str
    value: str
    note: str
    tone: str = "neutral"


@dataclass(frozen=True, slots=True)
class NextAction:
    """The single most useful thing to do next, stated plainly."""

    text: str
    endpoint: str | None = None
    link_label: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewCoverage:
    """Human-review coverage of one run, as a counted fraction.

    ``percent`` is the display rounding of reviewed/total — used only to
    size a gauge whose readable value is always the counted fraction.
    """

    reviewed: int
    total: int
    percent: int


@dataclass(frozen=True, slots=True)
class HealthSignal:
    """One explainable health signal derived from recorded run facts."""

    label: str
    value: str
    percent: int
    note: str
    tone: str = "neutral"


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """A recorded issue that needs a person, ordered by operational impact."""

    priority: str
    issue: str
    impact: str
    owner: str
    due: str
    endpoint: str | None = None
    link_label: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    """The workflow band and counted facts of one run."""

    steps: tuple[WorkflowStep, ...]
    counts: tuple[WorkspaceCount, ...]
    next_action: NextAction
    coverage: ReviewCoverage | None
    health: tuple[HealthSignal, ...]
    attention: tuple[AttentionItem, ...]


@dataclass(frozen=True, slots=True)
class RequirementWorkbenchView:
    """Server-rendered queue and selected requirement for focused review."""

    rows: tuple[AssessmentRow, ...]
    selected: AssessmentRow | None
    active_filter: str
    total: int
    pending: int
    mandatory: int
    evidence_gaps: int


def _step(key: str, label: str, state: str, note: str | None = None) -> WorkflowStep:
    return WorkflowStep(
        key=key, label=label, state=state, state_label=_STATE_LABELS[state], note=note
    )


def build_workspace_view(
    run: RunView,
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> WorkspaceView:
    """Project one run's recorded state onto the five-step bid workflow."""
    steps = _steps(run, assessment, package_section)
    return WorkspaceView(
        steps=steps,
        counts=_counts(assessment, package_section),
        next_action=_next_action(run, assessment, package_section),
        coverage=_coverage(assessment),
        health=_health(assessment, package_section),
        attention=_attention(run, assessment, package_section),
    )


def build_requirement_workbench(
    assessment: KnowledgeAssessmentView,
    requested_focus: str | None,
    requested_filter: str | None,
) -> RequirementWorkbenchView:
    """Select a safe queue/filter state without hiding the canonical rows."""
    active_filter = (
        requested_filter
        if requested_filter in {"all", "pending", "mandatory", "evidence-gaps"}
        else "all"
    )
    if active_filter == "pending":
        rows = tuple(row for row in assessment.rows if row.review.is_pending)
    elif active_filter == "mandatory":
        rows = tuple(row for row in assessment.rows if row.is_mandatory)
    elif active_filter == "evidence-gaps":
        rows = tuple(row for row in assessment.rows if not row.evidence)
    else:
        rows = assessment.rows

    selected = next(
        (row for row in rows if row.requirement_id == requested_focus),
        rows[0] if rows else None,
    )
    return RequirementWorkbenchView(
        rows=rows,
        selected=selected,
        active_filter=active_filter,
        total=len(assessment.rows),
        pending=sum(row.review.is_pending for row in assessment.rows),
        mandatory=sum(row.is_mandatory for row in assessment.rows),
        evidence_gaps=sum(not row.evidence for row in assessment.rows),
    )


def _coverage(assessment: KnowledgeAssessmentView | None) -> ReviewCoverage | None:
    if assessment is None or not assessment.rows:
        return None
    counts = assessment.review_counts
    reviewed = counts.confirmed + counts.rejected + counts.needs_clarification
    total = len(assessment.rows)
    return ReviewCoverage(reviewed=reviewed, total=total, percent=round(100 * reviewed / total))


def _ratio(value: int, total: int) -> int:
    return 0 if total == 0 else round(100 * value / total)


def _health(
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> tuple[HealthSignal, ...]:
    if assessment is None or not assessment.rows:
        return ()
    rows = assessment.rows
    total = len(rows)
    candidates = sum(row.match_status in _CANDIDATE_STATUSES for row in rows)
    evidenced = sum(bool(row.evidence) for row in rows)
    reviewed = total - assessment.review_counts.pending
    package = package_section.package if package_section is not None else None
    if package is None:
        package_percent = 0
        package_value = "Not generated"
        package_note = "A reviewed package has not been generated."
        package_tone = "warning"
    elif package.newer_reviews_exist:
        package_percent = _ratio(package.reviewed, package.total_requirements)
        package_value = f"v{package.package_version} stale"
        package_note = "The package predates the latest recorded review state."
        package_tone = "warning"
    else:
        package_percent = _ratio(package.reviewed, package.total_requirements)
        package_value = f"v{package.package_version}"
        package_note = package.state_label
        package_tone = "success" if package.is_complete else "warning"
    return (
        HealthSignal(
            "Candidate coverage",
            f"{candidates} / {total}",
            _ratio(candidates, total),
            "Requirements with a deterministic MATCHED or PARTIAL candidate; not a decision.",
            "success" if candidates == total else "warning",
        ),
        HealthSignal(
            "Evidence coverage",
            f"{evidenced} / {total}",
            _ratio(evidenced, total),
            "Requirements with at least one cited Golden Knowledge section.",
            "success" if evidenced == total else "warning",
        ),
        HealthSignal(
            "Human validation",
            f"{reviewed} / {total}",
            _ratio(reviewed, total),
            "Bid-scoped decisions recorded by a named reviewer.",
            "success" if reviewed == total else "warning",
        ),
        HealthSignal(
            "Package readiness",
            package_value,
            package_percent,
            package_note,
            package_tone,
        ),
    )


def _attention(
    run: RunView,
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> tuple[AttentionItem, ...]:
    items: list[AttentionItem] = []
    if run.is_blocked:
        items.append(
            AttentionItem(
                "HIGH",
                "Security gate blocked the package",
                "No downstream processing is permitted.",
                "Security reviewer",
                "Not recorded",
            )
        )
    elif run.is_security_review:
        items.append(
            AttentionItem(
                "HIGH",
                "Manual security decision pending",
                "Full analysis cannot start until the gate is resolved.",
                "Security reviewer",
                "Not recorded",
            )
        )
    elif run.is_quality_review:
        items.append(
            AttentionItem(
                "HIGH",
                "Quality gate requires review",
                "A complete bid working package was not produced.",
                "Bid reviewer",
                "Not recorded",
                "show_review_package",
                "Open review package",
            )
        )
    elif run.is_failed:
        items.append(
            AttentionItem(
                "HIGH",
                "Pipeline run failed",
                "The run produced no approved downstream package.",
                "Bid operations",
                "Not recorded",
            )
        )

    if assessment is not None:
        mandatory_pending = sum(
            row.is_mandatory and row.review.is_pending for row in assessment.rows
        )
        evidence_gaps = sum(not row.evidence for row in assessment.rows)
        candidate_gaps = sum(row.match_status not in _CANDIDATE_STATUSES for row in assessment.rows)
        if mandatory_pending:
            items.append(
                AttentionItem(
                    "HIGH",
                    f"{mandatory_pending} mandatory requirement(s) await review",
                    "Mandatory obligations have no recorded human decision.",
                    "Bid reviewer",
                    "Not recorded",
                    "show_knowledge_assessment",
                    "Review mandatory requirements",
                )
            )
        elif assessment.review_counts.pending:
            items.append(
                AttentionItem(
                    "MEDIUM",
                    f"{assessment.review_counts.pending} requirement(s) await review",
                    "The package cannot become review-complete.",
                    "Bid reviewer",
                    "Not recorded",
                    "show_knowledge_assessment",
                    "Open requirement review",
                )
            )
        if evidence_gaps:
            items.append(
                AttentionItem(
                    "HIGH",
                    f"{evidence_gaps} requirement(s) have no cited evidence",
                    "The candidate rationale is not supported by a knowledge reference.",
                    "Solution lead",
                    "Not recorded",
                    "show_knowledge_assessment",
                    "Inspect evidence gaps",
                )
            )
        if candidate_gaps:
            items.append(
                AttentionItem(
                    "MEDIUM",
                    f"{candidate_gaps} requirement(s) have no candidate match",
                    "Capability fit needs clarification or an explicit gap decision.",
                    "Solution lead",
                    "Not recorded",
                    "show_knowledge_assessment",
                    "Inspect candidate gaps",
                )
            )

    package = package_section.package if package_section is not None else None
    if package is not None and package.newer_reviews_exist:
        items.append(
            AttentionItem(
                "HIGH",
                "Reviewed package is stale",
                "A newer human review state exists than the generated package.",
                "Bid manager",
                "Not recorded",
                "show_working_package",
                "Generate the next version",
            )
        )
    return tuple(items)


def _steps(
    run: RunView,
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> tuple[WorkflowStep, ...]:
    if run.is_blocked:
        intake = _step("intake", "Intake", STATE_ATTENTION, "Blocked by the security gate")
    elif run.is_security_review:
        intake = _step("intake", "Intake", STATE_ATTENTION, "Manual security review required")
    else:
        intake = _step("intake", "Intake", STATE_COMPLETE, "Security gate cleared")

    if run.is_completed:
        requirements = _step(
            "requirements", "Requirements", STATE_COMPLETE, "Extracted and normalized"
        )
    elif run.is_failed or run.is_quality_review:
        requirements = _step(
            "requirements", "Requirements", STATE_ATTENTION, "Quality gate did not accept the run"
        )
    elif intake.state == STATE_ATTENTION:
        requirements = _step("requirements", "Requirements", STATE_PENDING)
    else:
        requirements = _step(
            "requirements", "Requirements", STATE_ACTIVE, "Full analysis not started"
        )

    if assessment is None:
        knowledge = _step("knowledge", "Knowledge Match", STATE_PENDING)
    elif not assessment.store_available:
        knowledge = _step(
            "knowledge", "Knowledge Match", STATE_ATTENTION, "Knowledge store not available"
        )
    else:
        knowledge = _step(
            "knowledge", "Knowledge Match", STATE_COMPLETE, "Candidates only — not decisions"
        )

    if assessment is None or not assessment.rows:
        review = _step("review", "Human Review", STATE_PENDING)
    elif not assessment.reviews_available:
        review = _step("review", "Human Review", STATE_ATTENTION, "Review records unavailable")
    elif assessment.review_counts.pending > 0:
        review = _step(
            "review",
            "Human Review",
            STATE_ACTIVE,
            f"{assessment.review_counts.pending} of {len(assessment.rows)} pending",
        )
    else:
        review = _step("review", "Human Review", STATE_COMPLETE, "Every assessment reviewed")

    package = package_section.package if package_section is not None else None
    if package is None:
        package_step = _step("package", "Working Package", STATE_PENDING, "Not generated yet")
    elif package.newer_reviews_exist:
        package_step = _step(
            "package", "Working Package", STATE_ATTENTION, "A newer review state exists"
        )
    else:
        package_step = _step(
            "package",
            "Working Package",
            STATE_COMPLETE,
            f"v{package.package_version} — {package.state_label}",
        )

    return (intake, requirements, knowledge, review, package_step)


def _counts(
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> tuple[WorkspaceCount, ...]:
    if assessment is None:
        return ()
    rows = assessment.rows
    counts = assessment.review_counts
    reviewed = counts.confirmed + counts.rejected + counts.needs_clarification
    candidates = sum(1 for row in rows if row.match_status in _CANDIDATE_STATUSES)
    evidence = sum(len(row.evidence) for row in rows)
    package = package_section.package if package_section is not None else None
    if package is None:
        package_value = "NOT GENERATED"
        package_note = "No reviewed working package yet"
        package_tone = "neutral"
    elif package.newer_reviews_exist:
        package_value = f"v{package.package_version} STALE"
        package_note = "A newer review state exists"
        package_tone = "warning"
    else:
        package_value = f"v{package.package_version}"
        package_note = package.state_label
        package_tone = "success" if package.is_complete else "warning"
    return (
        WorkspaceCount(
            label="Requirements", value=str(len(rows)), note="Extracted from this RFP package"
        ),
        WorkspaceCount(
            label="Candidate matches",
            value=str(candidates),
            note="Machine candidates — not decisions",
        ),
        WorkspaceCount(
            label="Needs review",
            value=str(counts.pending),
            note="No human decision recorded yet",
            tone="warning" if counts.pending else "neutral",
        ),
        WorkspaceCount(
            label="Reviewed",
            value=str(reviewed),
            note="Human decisions for this bid",
            tone="success" if reviewed else "neutral",
        ),
        WorkspaceCount(
            label="Evidence references", value=str(evidence), note="Cited knowledge sections"
        ),
        WorkspaceCount(
            label="Working package", value=package_value, note=package_note, tone=package_tone
        ),
    )


def _next_action(
    run: RunView,
    assessment: KnowledgeAssessmentView | None,
    package_section: ReviewedPackageSection | None,
) -> NextAction:
    if run.is_blocked:
        return NextAction(text="The package is blocked. No further processing is possible here.")
    if run.is_security_review:
        return NextAction(
            text=(
                "Resolve the manual security review. This interface cannot release "
                "a pending security decision."
            )
        )
    if run.is_failed:
        return NextAction(text="The run failed. Start a new run once the cause is addressed.")
    if run.is_quality_review:
        return NextAction(
            text="The quality gate requires manual review. Open the review package.",
            endpoint="show_review_package",
            link_label="Open review package",
        )
    if run.offer_full_analysis:
        return NextAction(
            text="Security checks passed. Run the full analysis to extract requirements."
        )
    if assessment is not None and assessment.review_counts.pending > 0:
        return NextAction(
            text=(
                f"{assessment.review_counts.pending} requirement assessment(s) "
                "await a human review decision."
            ),
            endpoint="show_knowledge_assessment",
            link_label="Open the review workspace",
        )
    package = package_section.package if package_section is not None else None
    can_generate = package_section is not None and package_section.can_generate
    if package is None and can_generate:
        return NextAction(
            text="All reviews are recorded. Generate the reviewed working package.",
            endpoint="show_working_package",
            link_label="Open working package",
        )
    if package is not None and package.newer_reviews_exist:
        return NextAction(
            text=(
                "A newer review state exists. Generate the next package version — "
                "existing versions remain unchanged."
            ),
            endpoint="show_working_package",
            link_label="Open working package",
        )
    if package is not None:
        return NextAction(
            text="The reviewed working package is up to date.",
            endpoint="show_working_package",
            link_label="Open working package",
        )
    return NextAction(text="No further action is recorded for this run.")
