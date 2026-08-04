"""Versioned MVP quality/coverage gate (Domain H).

``bidfusion-mvp-quality-gate:0.1.0`` runs after parsing, extraction, and
normalization but before the final working package. It separates *technical
execution* from *business usability*: a technically successful run that
produced measurably incomplete coverage must never look complete.

The gate uses only measurable technical signals — counts, warnings,
explicit stream accounting, provenance cross-checks — and never an invented
semantic accuracy score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from bidfusion.extraction.support import (
    cell_units,
    extraction_content_ref,
    extraction_domain,
    paragraph_units,
)
from bidfusion.normalization.merge import NORMALIZED_DOMAIN
from bidfusion.quality.coverage import ExtractionCoverage, compute_extraction_coverage
from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.schemas.common import BidfusionModel
from bidfusion.schemas.document import CanonicalDocument
from bidfusion.schemas.extraction import (
    DeadlineExtractionResult,
    ExtractionStream,
    FormalityExtractionResult,
    RequirementExtractionResult,
)
from bidfusion.schemas.ids import ArtifactId, BidId, RunId
from bidfusion.schemas.normalization import NormalizedBidDataset
from bidfusion.schemas.provenance import SourceReference
from bidfusion.shared.payloads import verify_sealed_artifact

QUALITY_GATE_NAME = "bidfusion-mvp-quality-gate"
QUALITY_GATE_VERSION = "0.4.0"
QUALITY_GATE_ID = f"{QUALITY_GATE_NAME}:{QUALITY_GATE_VERSION}"

#: Minimum number of canonical text units for "substantial text".
SUBSTANTIAL_TEXT_UNITS = 5

#: Coverage thresholds (documented, technical — no semantic scoring).
#: Any obligation candidate the extractors cannot account for requires
#: review: the MVP extractors are rule-based, so "unexplained" is an exact
#: technical statement, not a guess.
MAX_UNEXPLAINED_OBLIGATION_CANDIDATES = 0
#: With at least this many obligation candidates, a match ratio below
#: ``MIN_OBLIGATION_MATCH_RATIO`` is "measurably low coverage": one lucky
#: hit per stream must never make a mostly-missed document look complete.
MIN_OBLIGATION_CANDIDATES_FOR_RATIO = 5
MIN_OBLIGATION_MATCH_RATIO = 0.6
#: Deadline and formality streams use the same principle with their own
#: (lexical) candidate rules: with at least ``MIN_STREAM_CANDIDATES_FOR_RATIO``
#: candidates, a match ratio below ``MIN_STREAM_MATCH_RATIO`` — or any
#: unexplained candidate — is measurably low coverage. A nonempty stream is
#: therefore never automatically "covered enough".
MIN_STREAM_CANDIDATES_FOR_RATIO = 3
MIN_STREAM_MATCH_RATIO = 0.6
MAX_UNEXPLAINED_STREAM_CANDIDATES = 0

_UPPERCASE_OBLIGATION = re.compile(r"\b(MUST|SHALL)\b")
_REQUIREMENT_PREFIX = re.compile(r"^REQ-[A-Za-z0-9]+\b")

_FAILED_CODES = frozenset(
    {"extraction-stream-failed", "completeness-inconsistent", "provenance-unbound"}
)


class QualityGateStatus(StrEnum):
    """Business usability of one technically finished processing run."""

    ACCEPTABLE = "ACCEPTABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class QualitySignal(BidfusionModel):
    """One measurable coverage or integrity observation."""

    code: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    message: str = Field(min_length=1)
    affected: tuple[str, ...] = ()


class QualityGateReport(BidfusionModel):
    """Versioned outcome of the MVP quality gate.

    ``bid_id`` and ``run_id`` bind the report to exactly one run.
    ``dataset_artifact`` binds the evaluated normalized dataset by its full
    sealed reference — artifact ID, type, bid, run, content ref, *and*
    content hash — and the per-stream artifact references record exactly
    which sealed extraction results this gate evaluated. Downstream
    builders can therefore refuse reports that belong to a different run,
    a same-ID-but-altered dataset, or a different artifact set.
    """

    gate_name: str = Field(min_length=1)
    gate_version: str = Field(min_length=1)
    bid_id: BidId
    run_id: RunId
    dataset_artifact: ArtifactReference
    requirement_artifact: ArtifactReference | None
    deadline_artifact: ArtifactReference | None
    formality_artifact: ArtifactReference | None
    status: QualityGateStatus
    signals: tuple[QualitySignal, ...]
    coverage: ExtractionCoverage
    evaluated_at: datetime

    @property
    def dataset_artifact_id(self) -> ArtifactId:
        """Artifact ID of the evaluated dataset (convenience view)."""
        return self.dataset_artifact.artifact_id

    @property
    def evaluated_extraction_artifacts(self) -> tuple[ArtifactReference, ...]:
        """The exact sealed extraction artifacts this report evaluated."""
        return tuple(
            reference
            for reference in (
                self.requirement_artifact,
                self.deadline_artifact,
                self.formality_artifact,
            )
            if reference is not None
        )


@dataclass(frozen=True, slots=True)
class ParsedDocumentQuality:
    """Parse outcome of one successfully parsed document."""

    document_id: str
    filename: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnprocessedDocument:
    """A cleared document that could not be parsed (unsupported or failed)."""

    document_id: str
    filename: str
    reason: str


def evaluate_quality(
    *,
    parsed: tuple[ParsedDocumentQuality, ...],
    unprocessed: tuple[UnprocessedDocument, ...],
    canonicals: tuple[CanonicalDocument, ...],
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
    dataset: NormalizedBidDataset,
    evaluated_at: datetime,
) -> QualityGateReport:
    """Evaluate measurable coverage and integrity signals for one run."""
    signals: list[QualitySignal] = []

    for skipped in unprocessed:
        signals.append(
            QualitySignal(
                code="document-unprocessed",
                message=(
                    f"document {skipped.document_id} ({skipped.filename}) was cleared "
                    f"but not processed: {skipped.reason}"
                ),
                affected=(skipped.document_id,),
            )
        )
    for parsed_document in parsed:
        for warning in parsed_document.warnings:
            signals.append(
                QualitySignal(
                    code="parser-warning",
                    message=f"document {parsed_document.document_id}: {warning}",
                    affected=(parsed_document.document_id,),
                )
            )

    for canonical in canonicals:
        for page in canonical.pages:
            has_cells = any(row.cells for table in page.tables for row in table.rows)
            if not page.paragraphs and not has_cells:
                signals.append(
                    QualitySignal(
                        code="empty-page",
                        message=(
                            f"document {canonical.document_id} page {page.page_number} "
                            "has no extractable content"
                        ),
                        affected=(f"{canonical.document_id} p.{page.page_number}",),
                    )
                )

    completeness = dataset.completeness
    if completeness.failed_streams:
        failed_names = ", ".join(stream.value for stream in completeness.failed_streams)
        signals.append(
            QualitySignal(
                code="extraction-stream-failed",
                message=f"extraction stream(s) failed: {failed_names}",
                affected=tuple(stream.value for stream in completeness.failed_streams),
            )
        )
    results_by_stream: dict[ExtractionStream, object | None] = {
        ExtractionStream.REQUIREMENT: requirements,
        ExtractionStream.DEADLINE: deadlines,
        ExtractionStream.FORMALITY: formalities,
    }
    for stream, result in results_by_stream.items():
        claimed = stream in completeness.completed_streams
        if claimed and result is None:
            signals.append(
                QualitySignal(
                    code="completeness-inconsistent",
                    message=(
                        f"stream {stream.value} is accounted as completed "
                        "but no extraction result exists"
                    ),
                    affected=(stream.value,),
                )
            )
        if result is not None and not claimed:
            signals.append(
                QualitySignal(
                    code="completeness-inconsistent",
                    message=(
                        f"stream {stream.value} produced a result but is not accounted as completed"
                    ),
                    affected=(stream.value,),
                )
            )

    stream_counts: tuple[tuple[ExtractionStream, int | None], ...] = (
        (
            ExtractionStream.REQUIREMENT,
            None if requirements is None else len(requirements.requirements),
        ),
        (
            ExtractionStream.DEADLINE,
            None if deadlines is None else len(deadlines.deadlines),
        ),
        (
            ExtractionStream.FORMALITY,
            None if formalities is None else len(formalities.formalities),
        ),
    )
    for stream, count in stream_counts:
        if count == 0:
            signals.append(
                QualitySignal(
                    code="stream-empty",
                    message=f"expected stream {stream.value} completed with zero items",
                    affected=(stream.value,),
                )
            )

    coverage = compute_extraction_coverage(
        canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    if coverage.unexplained_candidates > MAX_UNEXPLAINED_OBLIGATION_CANDIDATES:
        signals.append(
            QualitySignal(
                code="unexplained-obligation-candidates",
                message=(
                    f"{coverage.unexplained_candidates} obligation candidate(s) of "
                    f"{coverage.obligation_candidates} were captured by no extraction "
                    f"stream (threshold: {MAX_UNEXPLAINED_OBLIGATION_CANDIDATES})"
                ),
            )
        )
    if (
        coverage.total_units_examined >= SUBSTANTIAL_TEXT_UNITS
        and coverage.obligation_candidates >= MIN_OBLIGATION_CANDIDATES_FOR_RATIO
        and coverage.obligation_matches
        < MIN_OBLIGATION_MATCH_RATIO * coverage.obligation_candidates
    ):
        signals.append(
            QualitySignal(
                code="low-obligation-coverage",
                message=(
                    f"only {coverage.obligation_matches} of "
                    f"{coverage.obligation_candidates} obligation candidates were "
                    f"captured over {coverage.total_units_examined} examined units "
                    f"(minimum ratio: {MIN_OBLIGATION_MATCH_RATIO})"
                ),
            )
        )
    for stream_label, candidates, matches, unexplained in (
        (
            "deadline",
            coverage.deadline_candidates,
            coverage.deadline_matches,
            coverage.unexplained_deadline_candidates,
        ),
        (
            "formality",
            coverage.formality_candidates,
            coverage.formality_matches,
            coverage.unexplained_formality_candidates,
        ),
    ):
        if unexplained > MAX_UNEXPLAINED_STREAM_CANDIDATES:
            signals.append(
                QualitySignal(
                    code=f"unexplained-{stream_label}-candidates",
                    message=(
                        f"{unexplained} {stream_label} candidate(s) of {candidates} "
                        f"were captured by no extraction result "
                        f"(threshold: {MAX_UNEXPLAINED_STREAM_CANDIDATES})"
                    ),
                )
            )
        if (
            candidates >= MIN_STREAM_CANDIDATES_FOR_RATIO
            and matches < MIN_STREAM_MATCH_RATIO * candidates
        ):
            signals.append(
                QualitySignal(
                    code=f"low-{stream_label}-coverage",
                    message=(
                        f"only {matches} of {candidates} {stream_label} candidates "
                        f"were captured (minimum ratio: {MIN_STREAM_MATCH_RATIO})"
                    ),
                )
            )

    text_units = tuple(
        unit
        for canonical in canonicals
        for unit in (*paragraph_units(canonical), *cell_units(canonical))
    )
    requirement_count = 0 if requirements is None else len(requirements.requirements)
    if len(text_units) >= SUBSTANTIAL_TEXT_UNITS and requirement_count == 0:
        signals.append(
            QualitySignal(
                code="no-requirements-despite-text",
                message=(
                    f"{len(text_units)} canonical text units were parsed but "
                    "zero requirements were recognized"
                ),
            )
        )

    captured_texts = _captured_texts(requirements, formalities)
    for unit in text_units:
        text = unit.text.strip()
        if not _UPPERCASE_OBLIGATION.search(text):
            continue
        # A bare modality cell ("MUST") is a table attribute, not an
        # obligation statement; require a minimal sentence length.
        if len(text.split()) < 3:
            continue
        if _REQUIREMENT_PREFIX.match(text) or text in captured_texts:
            continue
        signals.append(
            QualitySignal(
                code="obligation-without-requirement",
                message=(
                    "text unit contains an uppercase obligation keyword but "
                    f"produced no requirement: {_source_label(unit.source)}"
                ),
                affected=(_source_label(unit.source),),
            )
        )

    for conflict in dataset.unresolved_conflicts:
        signals.append(
            QualitySignal(
                code="unresolved-conflict",
                message=f"unresolved conflict {conflict.conflict_id}: {conflict.description}",
                affected=conflict.object_ids,
            )
        )

    canonical_ids = {canonical.artifact.artifact_id for canonical in canonicals}
    for reference in (
        *dataset.requirements,
        *dataset.deadlines,
        *dataset.formalities,
    ):
        for source in reference.sources:
            if source.canonical_artifact_id not in canonical_ids:
                signals.append(
                    QualitySignal(
                        code="provenance-unbound",
                        message=(
                            f"normalized object {reference.object_id} references an "
                            "unknown or missing canonical artifact"
                        ),
                        affected=(reference.object_id,),
                    )
                )

    if any(signal.code in _FAILED_CODES for signal in signals):
        status = QualityGateStatus.FAILED
    elif signals:
        status = QualityGateStatus.REVIEW_REQUIRED
    else:
        status = QualityGateStatus.ACCEPTABLE
    return QualityGateReport(
        gate_name=QUALITY_GATE_NAME,
        gate_version=QUALITY_GATE_VERSION,
        bid_id=dataset.bid_id,
        run_id=dataset.artifact.run_id,
        dataset_artifact=dataset.artifact.as_reference(),
        requirement_artifact=(
            None if requirements is None else requirements.artifact.as_reference()
        ),
        deadline_artifact=(None if deadlines is None else deadlines.artifact.as_reference()),
        formality_artifact=(None if formalities is None else formalities.artifact.as_reference()),
        status=status,
        signals=tuple(signals),
        coverage=coverage,
        evaluated_at=evaluated_at,
    )


def require_evaluated_artifacts(
    report: QualityGateReport,
    *,
    dataset: NormalizedBidDataset,
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
) -> None:
    """Fail closed unless the report evaluated exactly these sealed artifacts.

    Enforces, in order:

    - the provided dataset equals the report's ``dataset_artifact`` as a
      **full** reference (artifact ID, type, bid, run, content ref, content
      hash) and belongs to the report's own run and bid;
    - the dataset's sealed content hash still matches its payload, so a
      same-ID, same-hash dataset with mutated fields is rejected too;
    - per stream, the provided extraction result equals the recorded
      reference (full reference — missing, additional, foreign, swapped,
      or same-ID-different-hash results are all rejected), belongs to the
      **same run and bid** as the report and dataset, carries the expected
      stream content reference, and its seal still matches its payload;
    - the dataset's input lineage consists of exactly the evaluated
      extraction artifacts.
    """
    dataset_reference = dataset.artifact.as_reference()
    if dataset_reference != report.dataset_artifact:
        msg = (
            "the provided normalized dataset is not the one this quality "
            "gate report evaluated (artifact identity, run, or content "
            "hash differs)"
        )
        raise ValueError(msg)
    if (
        report.dataset_artifact.run_id != report.run_id
        or report.dataset_artifact.bid_id != report.bid_id
    ):
        msg = "the evaluated dataset belongs to a foreign run or bid"
        raise ValueError(msg)
    verify_sealed_artifact(dataset, domain=NORMALIZED_DOMAIN)

    evaluated: list[ArtifactReference] = []
    for stream_name, result, recorded in (
        ("requirement", requirements, report.requirement_artifact),
        ("deadline", deadlines, report.deadline_artifact),
        ("formality", formalities, report.formality_artifact),
    ):
        provided = None if result is None else result.artifact.as_reference()
        if provided != recorded:
            msg = (
                f"the provided {stream_name} extraction result is not the one "
                "this quality gate report evaluated"
            )
            raise ValueError(msg)
        if result is None or recorded is None:
            continue
        if recorded.run_id != report.run_id or recorded.bid_id != report.bid_id:
            msg = f"the evaluated {stream_name} artifact belongs to a foreign run or bid"
            raise ValueError(msg)
        if recorded.content_ref != extraction_content_ref(stream_name):
            msg = (
                f"the evaluated {stream_name} artifact does not carry the "
                f"expected {stream_name} stream content reference"
            )
            raise ValueError(msg)
        verify_sealed_artifact(result, domain=extraction_domain(stream_name))
        evaluated.append(recorded)
    if tuple(dataset.artifact.input_artifacts) != tuple(evaluated):
        msg = (
            "the normalized dataset's input lineage does not consist of "
            "exactly the extraction artifacts this quality gate report evaluated"
        )
        raise ValueError(msg)


def _captured_texts(
    requirements: RequirementExtractionResult | None,
    formalities: FormalityExtractionResult | None,
) -> frozenset[str]:
    captured: set[str] = set()
    if requirements is not None:
        for requirement in requirements.requirements:
            captured.add(requirement.original_text.strip())
            if requirement.normalized_text:
                captured.add(requirement.normalized_text.strip())
    if formalities is not None:
        for formality in formalities.formalities:
            captured.add(formality.original_text.strip())
            if formality.normalized_text:
                captured.add(formality.normalized_text.strip())
    return frozenset(captured)


def _source_label(source: SourceReference) -> str:
    locator = source.locator
    if locator.cell_id is not None:
        return f"{source.filename} ({locator.cell_id})"
    if locator.page is not None:
        return f"{source.filename} (p. {locator.page})"
    return source.filename
