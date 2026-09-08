"""Readable Markdown rendering of a Bid Working Package.

Every document-derived value — texts, descriptions, filenames, sheet and
cell labels — is untrusted and passes through
:func:`bidfusion.shared.markdown.sanitize_markdown_text` before it enters
the rendered output. There is no unsanitized insertion point.
"""

from __future__ import annotations

from bidfusion.schemas.extraction import Deadline, Requirement
from bidfusion.schemas.normalization import ExtractionCompleteness
from bidfusion.schemas.provenance import SourceReference
from bidfusion.schemas.working_package import EvidencedStatement, WorkingPackage
from bidfusion.shared.markdown import sanitize_markdown_text


def render_markdown(
    package: WorkingPackage,
    *,
    requirements: tuple[Requirement, ...],
    completeness: ExtractionCompleteness,
) -> str:
    """Render the working package as deterministic, human-readable Markdown.

    ``requirements`` are the normalized (deduplicated) requirement items in
    dataset order; they enrich the requirements table with the texts that
    the contract references by ID.
    """
    lines: list[str] = [
        f"# Bid Working Package — {package.bid_id}",
        "",
        f"- Generated: {package.generated_at.isoformat()}",
        f"- Run: {package.artifact.run_id}",
        f"- Source dataset: {package.source_dataset.artifact_id}",
        f"- Extraction completeness: {completeness.state.value} "
        f"({len(completeness.completed_streams)}/{len(completeness.expected_streams)} "
        "streams completed)",
        "",
        "## Timeline",
        "",
    ]
    if package.timeline:
        lines += [
            "| Due (UTC) | Kind | Description | Source |",
            "| --- | --- | --- | --- |",
        ]
        lines += [_timeline_row(deadline) for deadline in package.timeline]
    else:
        lines.append("No deadlines were extracted.")
    lines.append("")

    summary = package.requirements_summary
    lines += ["## Requirements", ""]
    lines.append(
        f"{summary.total} normalized requirement(s); "
        f"{len(package.critical_requirements)} mandatory (MUST)."
    )
    if summary.by_modality:
        lines.append(
            "By modality: "
            + ", ".join(
                f"{modality.value} {count}"
                for modality, count in sorted(
                    summary.by_modality.items(), key=lambda entry: entry[0].value
                )
            )
            + "."
        )
    if summary.by_category:
        lines.append(
            "By category: "
            + ", ".join(
                f"{category.value} {count}"
                for category, count in sorted(
                    summary.by_category.items(), key=lambda entry: entry[0].value
                )
            )
            + "."
        )
    lines.append("")
    if requirements:
        lines += [
            "| ID | Modality | Category | Requirement | Source |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [_requirement_row(requirement) for requirement in requirements]
        lines.append("")

    lines += ["## Submission instructions", ""]
    lines += _instruction_lines(package)
    lines.append("")

    lines += ["## Open questions", ""]
    if package.open_questions:
        lines += [
            f"- **{sanitize_markdown_text(question.question_id)}** "
            f"({sanitize_markdown_text(question.reason)}): "
            f"{sanitize_markdown_text(question.statement.text)} — "
            f"{_statement_sources(question.statement)}"
            for question in package.open_questions
        ]
    else:
        lines.append("No open questions were raised.")
    lines.append("")
    return "\n".join(lines)


def _timeline_row(deadline: Deadline) -> str:
    due = deadline.due_at.strftime("%Y-%m-%d %H:%M")
    description = sanitize_markdown_text(deadline.description or "") or "—"
    return f"| {due} | {deadline.kind.value} | {description} | {_source_label(deadline.source)} |"


def _requirement_row(requirement: Requirement) -> str:
    text = sanitize_markdown_text(requirement.normalized_text or requirement.original_text)
    return (
        f"| {requirement.requirement_id} | {requirement.modality.value} "
        f"| {requirement.category.value} | {text} | {_source_label(requirement.source)} |"
    )


def _instruction_lines(package: WorkingPackage) -> list[str]:
    instructions = package.submission_instructions
    groups: tuple[tuple[str, tuple[EvidencedStatement, ...]], ...] = (
        ("Portal", (instructions.portal,) if instructions.portal else ()),
        ("Submission process", instructions.upload_process),
        ("Required formats", instructions.formats),
        ("Signatures", instructions.signatures_required),
        ("Special requirements", instructions.special_requirements),
    )
    lines: list[str] = []
    for label, statements in groups:
        lines += [
            f"- **{label}:** {sanitize_markdown_text(statement.text)} — "
            f"{_statement_sources(statement)}"
            for statement in statements
        ]
    if not lines:
        lines.append("No submission formalities were extracted.")
    return lines


def _statement_sources(statement: EvidencedStatement) -> str:
    return "; ".join(_source_label(source) for source in statement.sources)


def _source_label(source: SourceReference) -> str:
    locator = source.locator
    filename = sanitize_markdown_text(source.filename)
    if locator.cell_id is not None:
        return f"{filename} ({sanitize_markdown_text(locator.cell_id)})"
    if locator.page is not None:
        return f"{filename} (p. {locator.page})"
    return filename
