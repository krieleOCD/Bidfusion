"""Tests for the versioned MVP quality/coverage gate (F3)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.normalization import merge_extractions
from bidfusion.quality import (
    QUALITY_GATE_NAME,
    QUALITY_GATE_VERSION,
    ParsedDocumentQuality,
    QualityGateReport,
    QualityGateStatus,
    UnprocessedDocument,
    build_review_package,
    evaluate_quality,
)
from bidfusion.schemas import (
    CanonicalDocument,
    DeadlineExtractionResult,
    ExtractionStream,
    FormalityExtractionResult,
    NormalizedBidDataset,
    RequirementExtractionResult,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def extract_all(
    canonicals: tuple[CanonicalDocument, ...],
) -> tuple[RequirementExtractionResult, DeadlineExtractionResult, FormalityExtractionResult]:
    return (
        extract_requirements(
            canonicals,
            bid_id=BID_ID,
            run_id=RUN_ID,
            artifact_id="ART-20260804-000051",
            created_at=NOW,
        ),
        extract_deadlines(
            canonicals,
            bid_id=BID_ID,
            run_id=RUN_ID,
            artifact_id="ART-20260804-000052",
            created_at=NOW,
        ),
        extract_formalities(
            canonicals,
            bid_id=BID_ID,
            run_id=RUN_ID,
            artifact_id="ART-20260804-000053",
            created_at=NOW,
        ),
    )


def merge_all(
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
    *,
    failed: tuple[ExtractionStream, ...] = (),
) -> NormalizedBidDataset:
    return merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000054",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        failed_streams=failed,
    )


def evaluate(
    canonicals: tuple[CanonicalDocument, ...],
    requirements: RequirementExtractionResult | None,
    deadlines: DeadlineExtractionResult | None,
    formalities: FormalityExtractionResult | None,
    dataset: NormalizedBidDataset,
    *,
    parsed: tuple[ParsedDocumentQuality, ...] = (),
    unprocessed: tuple[UnprocessedDocument, ...] = (),
) -> QualityGateReport:
    return evaluate_quality(
        parsed=parsed,
        unprocessed=unprocessed,
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )


def codes(report: QualityGateReport) -> set[str]:
    return {signal.code for signal in report.signals}


def test_clean_minimal_chain_is_acceptable(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, formalities, dataset)

    assert report.gate_name == QUALITY_GATE_NAME
    assert report.gate_version == QUALITY_GATE_VERSION
    assert report.signals == ()
    assert report.status is QualityGateStatus.ACCEPTABLE


def test_quality_fixture_collects_all_expected_review_signals(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_quality_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    parsed = tuple(
        ParsedDocumentQuality(
            document_id=canonical.document_id,
            filename=canonical.source.filename,
            warnings=("page 2 contains no extractable text",)
            if canonical.source.filename.endswith(".pdf")
            else ("formula without stored value skipped at Calc!C1",),
        )
        for canonical in rfp_quality_canonicals
    )

    report = evaluate(
        rfp_quality_canonicals,
        requirements,
        deadlines,
        formalities,
        dataset,
        parsed=parsed,
    )

    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert {
        "parser-warning",
        "empty-page",
        "obligation-without-requirement",
        "unresolved-conflict",
        "stream-empty",
    } <= codes(report)
    obligation = next(
        signal for signal in report.signals if signal.code == "obligation-without-requirement"
    )
    assert "mixed-scan.pdf (p. 1)" in obligation.message


def test_zero_requirements_despite_substantial_text_requires_review(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    empty_requirements, empty_deadlines, empty_formalities = extract_all(())
    dataset = merge_all(empty_requirements, empty_deadlines, empty_formalities)

    report = evaluate(
        rfp_minimal_canonicals,
        empty_requirements,
        empty_deadlines,
        empty_formalities,
        dataset,
    )

    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert "no-requirements-despite-text" in codes(report)
    assert "stream-empty" in codes(report)


def test_unprocessed_documents_require_review() -> None:
    empty_requirements, empty_deadlines, empty_formalities = extract_all(())
    dataset = merge_all(empty_requirements, empty_deadlines, empty_formalities)

    report = evaluate(
        (),
        empty_requirements,
        empty_deadlines,
        empty_formalities,
        dataset,
        unprocessed=(
            UnprocessedDocument(
                document_id="DOC-001",
                filename="blank-scan.pdf",
                reason="PDF contains no extractable text",
            ),
        ),
    )

    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert "document-unprocessed" in codes(report)


def test_partially_failed_streams_fail_the_quality_gate(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, _ = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, None, failed=(ExtractionStream.FORMALITY,))

    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, None, dataset)

    assert report.status is QualityGateStatus.FAILED
    assert "extraction-stream-failed" in codes(report)


def test_inconsistent_completeness_accounting_fails_the_quality_gate(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, None, dataset)

    assert report.status is QualityGateStatus.FAILED
    assert "completeness-inconsistent" in codes(report)


def test_unbound_provenance_fails_the_quality_gate(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate((), requirements, deadlines, formalities, dataset)

    assert report.status is QualityGateStatus.FAILED
    assert "provenance-unbound" in codes(report)


def test_clean_chain_reports_full_measured_coverage(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, formalities, dataset)

    coverage = report.coverage
    assert coverage.total_units_examined == 28
    assert coverage.obligation_candidates == 14
    assert coverage.obligation_matches == 14
    assert coverage.unexplained_candidates == 0
    assert coverage.deadline_candidates == 5
    assert coverage.deadline_matches == 5
    assert coverage.formality_candidates == 6
    assert coverage.formality_matches == 6
    assert report.bid_id == BID_ID
    assert report.run_id == RUN_ID
    assert report.dataset_artifact == dataset.artifact.as_reference()
    assert report.status is QualityGateStatus.ACCEPTABLE


def test_one_hit_per_stream_with_many_missed_lowercase_and_german_obligations(
    tmp_path: Path,
    canonicals_builder: Callable[..., tuple[CanonicalDocument, ...]],
) -> None:
    """One hit per stream must not mask measurably low coverage."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "notes.txt").write_text(
        "\n".join(
            [
                "REQ-A1: The supplier MUST provide a status report.",
                "Submission deadline: 2026-09-30 17:00",
                "Offers must be submitted via the procurement portal.",
                # v0.3 detects plain modal statements, so the uncovered
                # candidates below use shapes the extractor declines:
                # party-less possibilities and subjunctive phrasing.
                "additional improvements may be proposed by any vendor.",
                "weitere optionen können der anlage entnommen werden.",
                "die dokumentation sollte regelmäßig geprüft werden.",
                "die preise sollten transparent aufgeschlüsselt werden.",
                "suppliers may propose additional improvements.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    canonicals = canonicals_builder(package, ("notes.txt",))
    requirements, deadlines, formalities = extract_all(canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(canonicals, requirements, deadlines, formalities, dataset)

    # Every stream produced at least one item …
    assert requirements.requirements and deadlines.deadlines and formalities.formalities
    # … yet the run is measurably incomplete and must be reviewed.
    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert {"unexplained-obligation-candidates", "low-obligation-coverage"} <= codes(report)
    coverage = report.coverage
    assert coverage.obligation_candidates == 7
    assert coverage.obligation_matches == 2
    assert coverage.unexplained_candidates == 5
    assert coverage.deadline_candidates == 1
    assert coverage.deadline_matches == 1


def test_table_rows_count_as_obligation_candidates(
    tmp_path: Path,
    canonicals_builder: Callable[..., tuple[CanonicalDocument, ...]],
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Anforderungen"
    sheet.append(["ID", "Anforderung", "Modalität"])
    sheet.append(["REQ-D1", "Der Anbieter muss ein Ticketsystem bereitstellen.", "muss"])
    sheet.append(["", "Die Lösung soll Single Sign-on unterstützen.", ""])
    workbook.save(package / "matrix.xlsx")

    canonicals = canonicals_builder(package, ("matrix.xlsx",))
    requirements, deadlines, formalities = extract_all(canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(canonicals, requirements, deadlines, formalities, dataset)

    coverage = report.coverage
    assert coverage.obligation_candidates == 2, "both table rows are candidates"
    assert coverage.obligation_matches == 2, "v0.2 captures the unlabelled row too"
    assert coverage.unexplained_candidates == 0
    assert "unexplained-obligation-candidates" not in codes(report)


def test_one_of_five_deadline_candidates_requires_review(
    tmp_path: Path,
    canonicals_builder: Callable[..., tuple[CanonicalDocument, ...]],
) -> None:
    """A nonempty deadline stream with low measured coverage must be reviewed."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dates.txt").write_text(
        "\n".join(
            [
                "Submission deadline: 2026-09-30 17:00",
                "Q&A deadline: 2026-09-11 12:00",
                "Presentation: 2026-10-15 14:00",
                "Contract start: 2027-01-01",
                "Site visit: 05.09.2026",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    canonicals = canonicals_builder(package, ("dates.txt",))
    requirements, deadlines, formalities = extract_all(canonicals)
    assert len(deadlines.deadlines) == 5
    # Simulate a weaker extractor that recognized only one of five dates.
    partial_deadlines = deadlines.model_copy(update={"deadlines": deadlines.deadlines[:1]})
    dataset = merge_all(requirements, partial_deadlines, formalities)

    report = evaluate(canonicals, requirements, partial_deadlines, formalities, dataset)

    coverage = report.coverage
    assert coverage.deadline_candidates == 5
    assert coverage.deadline_matches == 1
    assert coverage.unexplained_deadline_candidates == 4
    assert coverage.deadline_match_ratio == 0.2
    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert {"unexplained-deadline-candidates", "low-deadline-coverage"} <= codes(report)


def test_one_of_several_formality_candidates_requires_review(
    tmp_path: Path,
    canonicals_builder: Callable[..., tuple[CanonicalDocument, ...]],
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "formalities.txt").write_text(
        "\n".join(
            [
                "Offers must be submitted via the procurement portal.",
                "The offer letter must be signed by the representative.",
                "Proposals are delivered as PDF format only.",
                "Late submission leads to exclusion.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    canonicals = canonicals_builder(package, ("formalities.txt",))
    requirements, deadlines, formalities = extract_all(canonicals)
    assert len(formalities.formalities) == 4
    partial_formalities = formalities.model_copy(
        update={"formalities": formalities.formalities[:1]}
    )
    dataset = merge_all(requirements, deadlines, partial_formalities)

    report = evaluate(canonicals, requirements, deadlines, partial_formalities, dataset)

    coverage = report.coverage
    assert coverage.formality_candidates == 4
    assert coverage.formality_matches == 1
    assert coverage.unexplained_formality_candidates == 3
    assert coverage.formality_match_ratio == 0.25
    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    assert {"unexplained-formality-candidates", "low-formality-coverage"} <= codes(report)


def test_clean_chain_reports_full_stream_ratios(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)

    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, formalities, dataset)

    coverage = report.coverage
    assert coverage.deadline_match_ratio == 1.0
    assert coverage.formality_match_ratio == 1.0
    assert coverage.obligation_match_ratio == 1.0
    assert coverage.unexplained_deadline_candidates == 0
    assert coverage.unexplained_formality_candidates == 0
    assert report.status is QualityGateStatus.ACCEPTABLE


def test_review_package_requires_exactly_a_review_required_report(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    acceptable = evaluate(rfp_minimal_canonicals, requirements, deadlines, formalities, dataset)
    assert acceptable.status is QualityGateStatus.ACCEPTABLE

    for status in (QualityGateStatus.ACCEPTABLE, QualityGateStatus.FAILED):
        report = acceptable.model_copy(update={"status": status})
        with pytest.raises(ValueError, match="REVIEW_REQUIRED"):
            build_review_package(
                report,
                bid_id=BID_ID,
                run_id=RUN_ID,
                generated_at=NOW,
                requirements=requirements,
                deadlines=deadlines,
                formalities=formalities,
                dataset=dataset,
                parser_warnings=(),
            )


def test_review_package_requires_the_exact_evaluated_artifacts(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_quality_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    report = evaluate(rfp_quality_canonicals, requirements, deadlines, formalities, dataset)
    assert report.status is QualityGateStatus.REVIEW_REQUIRED

    # Missing stream: the gate evaluated a formality artifact, none provided.
    with pytest.raises(ValueError, match="not the one"):
        build_review_package(
            report,
            bid_id=BID_ID,
            run_id=RUN_ID,
            generated_at=NOW,
            requirements=requirements,
            deadlines=deadlines,
            formalities=None,
            dataset=dataset,
            parser_warnings=(),
        )


def test_review_package_refuses_foreign_run_extraction_artifacts(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    """Same-run lineage holds for the review builder as well."""
    foreign_formalities = extract_formalities(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id="RUN-20260805-0002",
        artifact_id="ART-20260805-000053",
        created_at=NOW,
    )
    requirements, deadlines, _ = extract_all(rfp_minimal_canonicals)
    dataset = merge_all(requirements, deadlines, foreign_formalities)
    report = evaluate(rfp_minimal_canonicals, requirements, deadlines, foreign_formalities, dataset)
    review_report = report.model_copy(update={"status": QualityGateStatus.REVIEW_REQUIRED})

    with pytest.raises(ValueError, match="foreign run"):
        build_review_package(
            review_report,
            bid_id=BID_ID,
            run_id=RUN_ID,
            generated_at=NOW,
            requirements=requirements,
            deadlines=deadlines,
            formalities=foreign_formalities,
            dataset=dataset,
            parser_warnings=(),
        )


def test_review_package_refuses_a_same_id_dataset_with_altered_content(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_quality_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    report = evaluate(rfp_quality_canonicals, requirements, deadlines, formalities, dataset)
    assert report.status is QualityGateStatus.REVIEW_REQUIRED
    stripped = dataset.model_copy(update={"requirements": ()})

    with pytest.raises(ValueError, match="content hash"):
        build_review_package(
            report,
            bid_id=BID_ID,
            run_id=RUN_ID,
            generated_at=NOW,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            dataset=stripped,
            parser_warnings=(),
        )


def test_review_package_builds_with_exact_lineage(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_quality_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    report = evaluate(rfp_quality_canonicals, requirements, deadlines, formalities, dataset)
    assert report.status is QualityGateStatus.REVIEW_REQUIRED

    review = build_review_package(
        report,
        bid_id=BID_ID,
        run_id=RUN_ID,
        generated_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        parser_warnings=(),
    )

    assert review.status == "REVIEW_REQUIRED"
    assert review.detected_requirements


def test_review_package_requires_a_matching_run_bid_and_dataset(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = extract_all(rfp_quality_canonicals)
    dataset = merge_all(requirements, deadlines, formalities)
    report = evaluate(rfp_quality_canonicals, requirements, deadlines, formalities, dataset)
    assert report.status is QualityGateStatus.REVIEW_REQUIRED

    foreign_dataset_reference = report.dataset_artifact.model_copy(
        update={"artifact_id": "ART-20260804-999999"}
    )
    for update, message in (
        ({"run_id": "RUN-20260805-0002"}, "run"),
        ({"dataset_artifact": foreign_dataset_reference}, "dataset"),
        ({"bid_id": "BID-2026-000999"}, "bid"),
    ):
        with pytest.raises(ValueError, match=message):
            build_review_package(
                report.model_copy(update=update),
                bid_id=BID_ID,
                run_id=RUN_ID,
                generated_at=NOW,
                requirements=requirements,
                deadlines=deadlines,
                formalities=formalities,
                dataset=dataset,
                parser_warnings=(),
            )
