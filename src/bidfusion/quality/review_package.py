"""Review package: the explicit non-complete output for REVIEW_REQUIRED runs.

This is a small, versioned control-plane contract of the quality domain —
deliberately **not** an imitation of the business ``WorkingPackage``
schema. It exists so a run that needs manual review still hands reviewers
everything that was reliably detected (with sources), together with the
reasons, warnings, and required manual actions. It is unambiguously marked
as *not* a complete bid working package.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Final, Literal

from pydantic import Field

from bidfusion.quality.gate import (
    QualityGateReport,
    QualityGateStatus,
    require_evaluated_artifacts,
)
from bidfusion.schemas.common import BidfusionModel
from bidfusion.schemas.extraction import (
    DeadlineExtractionResult,
    FormalityExtractionResult,
    RequirementExtractionResult,
)
from bidfusion.schemas.ids import BidId, RunId
from bidfusion.schemas.normalization import NormalizedBidDataset
from bidfusion.schemas.provenance import SourceReference
from bidfusion.shared.markdown import sanitize_markdown_text

REVIEW_PACKAGE_SCHEMA_VERSION: Final = "0.1.0"
REVIEW_PACKAGE_NOTICE: Final = "NOT A COMPLETE BID WORKING PACKAGE"

_MANUAL_ACTIONS_BY_CODE = {
    "document-unprocessed": (
        "Review the unprocessed documents manually; OCR and further parsers "
        "are outside the MVP scope."
    ),
    "parser-warning": (
        "Verify the pages and sheets behind every parser warning against the original documents."
    ),
    "empty-page": (
        "Verify the pages and sheets behind every parser warning against the original documents."
    ),
    "stream-empty": (
        "Extract the missing requirements, deadlines, or formalities manually "
        "for the affected documents."
    ),
    "no-requirements-despite-text": (
        "Extract the missing requirements, deadlines, or formalities manually "
        "for the affected documents."
    ),
    "obligation-without-requirement": (
        "Classify the obligation statements that the rule-based extractor could not capture."
    ),
    "unexplained-obligation-candidates": (
        "Classify the obligation statements that the rule-based extractor could not capture."
    ),
    "low-obligation-coverage": (
        "Classify the obligation statements that the rule-based extractor could not capture."
    ),
    "unresolved-conflict": (
        "Resolve the conflicting duplicate statements and record the authoritative value."
    ),
}
_FALLBACK_ACTION = "Review the quality-gate signals and decide on manual follow-up."


class DetectedItem(BidfusionModel):
    """One reliably detected content item, always with its sources."""

    text: str = Field(min_length=1)
    sources: tuple[str, ...] = Field(min_length=1)


class ReviewPackage(BidfusionModel):
    """Versioned quality-domain record of an incomplete, review-bound run."""

    notice: Literal["NOT A COMPLETE BID WORKING PACKAGE"] = REVIEW_PACKAGE_NOTICE
    schema_version: Literal["0.1.0"] = REVIEW_PACKAGE_SCHEMA_VERSION
    status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    quality_gate_name: str = Field(min_length=1)
    quality_gate_version: str = Field(min_length=1)
    bid_id: BidId
    run_id: RunId
    generated_at: datetime
    reasons: tuple[str, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    affected_documents: tuple[str, ...] = ()
    affected_sources: tuple[str, ...] = ()
    detected_requirements: tuple[DetectedItem, ...] = ()
    detected_deadlines: tuple[DetectedItem, ...] = ()
    detected_formalities: tuple[DetectedItem, ...] = ()
    unresolved_conflicts: tuple[str, ...] = ()
    required_manual_actions: tuple[str, ...] = Field(min_length=1)


def build_review_package(
    report: QualityGateReport,
    *,
    bid_id: BidId,
    run_id: RunId,
    generated_at: datetime,
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
    dataset: NormalizedBidDataset,
    parser_warnings: tuple[str, ...],
) -> ReviewPackage:
    """Assemble the review package from the quality report and detections.

    Only a report with status ``REVIEW_REQUIRED`` can become a review
    package: a ``FAILED`` (or ``ACCEPTABLE``) run must never be relabelled.
    The report must also belong to exactly this run and dataset, and the
    provided extraction results must be exactly the sealed artifacts the
    gate evaluated.
    """
    if report.status is not QualityGateStatus.REVIEW_REQUIRED:
        msg = (
            "a review package requires a quality gate report with status "
            f"REVIEW_REQUIRED, got {report.status.value}"
        )
        raise ValueError(msg)
    _require_matching_report(report, bid_id=bid_id, run_id=run_id, dataset=dataset)
    require_evaluated_artifacts(
        report,
        dataset=dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    requirement_items: dict[str, tuple[str, tuple[SourceReference, ...]]] = {
        item.requirement_id: (item.normalized_text or item.original_text, (item.source,))
        for item in (requirements.requirements if requirements is not None else ())
    }
    deadline_items: dict[str, tuple[str, tuple[SourceReference, ...]]] = {
        item.deadline_id: (
            f"{item.due_at.strftime('%Y-%m-%d %H:%M')} UTC — "
            f"{item.kind.value}: {item.description or 'no description'}",
            (item.source,),
        )
        for item in (deadlines.deadlines if deadlines is not None else ())
    }
    formality_items: dict[str, tuple[str, tuple[SourceReference, ...]]] = {
        item.formality_id: (
            f"{item.kind.value}: {item.normalized_text or item.original_text}",
            (item.source,),
        )
        for item in (formalities.formalities if formalities is not None else ())
    }

    actions = sorted(
        {_MANUAL_ACTIONS_BY_CODE.get(signal.code, _FALLBACK_ACTION) for signal in report.signals}
    )
    return ReviewPackage(
        quality_gate_name=report.gate_name,
        quality_gate_version=report.gate_version,
        bid_id=bid_id,
        run_id=run_id,
        generated_at=generated_at,
        reasons=tuple(signal.message for signal in report.signals) or ("unspecified",),
        warnings=parser_warnings,
        affected_documents=_unique(
            label
            for signal in report.signals
            for label in signal.affected
            if label.startswith("DOC-")
        ),
        affected_sources=_unique(
            label
            for signal in report.signals
            for label in signal.affected
            if not label.startswith("DOC-")
        ),
        detected_requirements=_detected(dataset_ids(dataset, "requirements"), requirement_items),
        detected_deadlines=_detected(dataset_ids(dataset, "deadlines"), deadline_items),
        detected_formalities=_detected(dataset_ids(dataset, "formalities"), formality_items),
        unresolved_conflicts=tuple(
            f"{conflict.conflict_id}: {conflict.description}"
            for conflict in dataset.unresolved_conflicts
        ),
        required_manual_actions=tuple(actions) or (_FALLBACK_ACTION,),
    )


def _require_matching_report(
    report: QualityGateReport,
    *,
    bid_id: BidId,
    run_id: RunId,
    dataset: NormalizedBidDataset,
) -> None:
    """Fail closed unless the report belongs to this run and bid.

    The full dataset binding — including the dataset's content hash — is
    enforced by :func:`bidfusion.quality.gate.require_evaluated_artifacts`.
    """
    if report.bid_id != bid_id or dataset.bid_id != bid_id:
        msg = "the quality gate report does not belong to this bid"
        raise ValueError(msg)
    if report.run_id != run_id or dataset.artifact.run_id != run_id:
        msg = "the quality gate report does not belong to this run"
        raise ValueError(msg)


def dataset_ids(dataset: NormalizedBidDataset, collection: str) -> tuple[str, ...]:
    """Normalized object IDs of one dataset collection, in dataset order."""
    references = {
        "requirements": dataset.requirements,
        "deadlines": dataset.deadlines,
        "formalities": dataset.formalities,
    }[collection]
    return tuple(reference.object_id for reference in references)


def render_review_markdown(package: ReviewPackage) -> str:
    """Render the review package as sanitized, unambiguous Markdown."""
    lines: list[str] = [
        f"# Review Package — {package.bid_id}",
        "",
        f"> **{package.notice} — MANUAL REVIEW REQUIRED.**",
        "> This run did not pass the quality gate; content below is partial.",
        "",
        f"- Status: {package.status}",
        f"- Quality gate: {package.quality_gate_name} {package.quality_gate_version}",
        f"- Run: {package.run_id}",
        f"- Generated: {package.generated_at.isoformat()}",
        "",
        "## Reasons",
        "",
    ]
    lines += [f"- {sanitize_markdown_text(reason)}" for reason in package.reasons]
    lines += ["", "## Required manual actions", ""]
    lines += [f"- {sanitize_markdown_text(action)}" for action in package.required_manual_actions]

    if package.warnings:
        lines += ["", "## Parser warnings", ""]
        lines += [f"- {sanitize_markdown_text(warning)}" for warning in package.warnings]
    if package.affected_documents or package.affected_sources:
        lines += ["", "## Affected documents and sources", ""]
        lines += [
            f"- {sanitize_markdown_text(label)}"
            for label in (*package.affected_documents, *package.affected_sources)
        ]
    for title, items in (
        ("Detected requirements (partial)", package.detected_requirements),
        ("Detected deadlines (partial)", package.detected_deadlines),
        ("Detected formalities (partial)", package.detected_formalities),
    ):
        lines += ["", f"## {title}", ""]
        if items:
            lines += [
                f"- {sanitize_markdown_text(item.text)} — "
                + "; ".join(sanitize_markdown_text(source) for source in item.sources)
                for item in items
            ]
        else:
            lines.append("None detected.")
    if package.unresolved_conflicts:
        lines += ["", "## Unresolved conflicts", ""]
        lines += [
            f"- {sanitize_markdown_text(conflict)}" for conflict in package.unresolved_conflicts
        ]
    lines.append("")
    return "\n".join(lines)


def _detected(
    object_ids: tuple[str, ...],
    items: Mapping[str, tuple[str, tuple[SourceReference, ...]]],
) -> tuple[DetectedItem, ...]:
    detected: list[DetectedItem] = []
    for object_id in object_ids:
        entry = items.get(object_id)
        if entry is None:
            continue
        text, sources = entry
        detected.append(
            DetectedItem(
                text=text,
                sources=tuple(_source_label(source) for source in sources),
            )
        )
    return tuple(detected)


def _source_label(source: SourceReference) -> str:
    locator = source.locator
    if locator.cell_id is not None:
        return f"{source.filename} ({locator.cell_id})"
    if locator.page is not None:
        return f"{source.filename} (p. {locator.page})"
    return source.filename


def _unique(labels: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for label in labels:
        seen.setdefault(label, None)
    return tuple(seen)
