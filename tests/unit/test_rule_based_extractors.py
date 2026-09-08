"""Tests for the deterministic rule-based extraction slice."""

from __future__ import annotations

from datetime import UTC, datetime

from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.schemas import (
    CanonicalDocument,
    DeadlineKind,
    FormalityKind,
    RequirementCategory,
    RequirementModality,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_requirement_extraction_covers_pdf_xlsx_and_txt_with_provenance(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract_requirements(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000021",
        created_at=NOW,
    )

    assert len(result.requirements) == 9
    assert [item.requirement_id for item in result.requirements[:3]] == [
        "REQ-000001",
        "REQ-000002",
        "REQ-000003",
    ]

    pdf_must = result.requirements[1]
    assert pdf_must.original_text.startswith("REQ-P2:")
    assert pdf_must.modality is RequirementModality.MUST
    assert pdf_must.category is RequirementCategory.SECURITY
    assert pdf_must.source.locator.page == 2
    assert pdf_must.source.canonical_artifact_id == (rfp_minimal_canonicals[0].artifact.artifact_id)

    unclear = result.requirements[4]
    assert unclear.original_text.startswith("REQ-P5:")
    assert unclear.modality is RequirementModality.UNKNOWN
    assert unclear.confidence == 0.4

    xlsx_first = result.requirements[5]
    assert xlsx_first.normalized_text == (
        "The supplier MUST provide a German-speaking service desk."
    )
    assert xlsx_first.modality is RequirementModality.MUST
    assert xlsx_first.source.locator.cell_id == "Requirements!B2"

    duplicate_pair = (result.requirements[1], result.requirements[7])
    assert duplicate_pair[0].normalized_text == duplicate_pair[1].normalized_text

    txt_requirement = result.requirements[8]
    assert txt_requirement.original_text.startswith("REQ-T1:")
    assert txt_requirement.source.locator.paragraph_id is not None


def test_deadline_extraction_reads_iso_dates_from_pdf_and_xlsx(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract_deadlines(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000022",
        created_at=NOW,
    )

    assert [deadline.kind for deadline in result.deadlines] == [
        DeadlineKind.SUBMISSION,
        DeadlineKind.QA,
        DeadlineKind.CONTRACT_START,
        DeadlineKind.OTHER,
        DeadlineKind.PRESENTATION,
    ]
    submission = result.deadlines[0]
    assert submission.due_at == datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
    assert submission.source.locator.page == 1

    contract_start = result.deadlines[2]
    assert contract_start.due_at == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)

    site_visit = result.deadlines[3]
    assert site_visit.description == "Site visit"
    assert site_visit.due_at == datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    assert site_visit.source.locator.cell_id == "Timeline!B2"


def test_formality_extraction_classifies_kinds_and_skips_requirements(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract_formalities(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000023",
        created_at=NOW,
    )

    assert [formality.kind for formality in result.formalities] == [
        FormalityKind.PORTAL_REQUIREMENT,
        FormalityKind.REQUIRED_FORMAT,
        FormalityKind.SIGNATURE_REQUIREMENT,
        FormalityKind.REQUIRED_FORMAT,
        FormalityKind.REQUIRED_FORMAT,
        FormalityKind.SUBMISSION_INSTRUCTION,
    ]
    assert all(not formality.original_text.startswith("REQ-") for formality in result.formalities)
    xlsx_format = result.formalities[3]
    assert xlsx_format.source.locator.cell_id == "Formalities!A2"
    late_submission = result.formalities[5]
    assert late_submission.original_text.startswith("Late submissions")


def test_extraction_over_no_documents_is_an_explicit_empty_result() -> None:
    result = extract_requirements(
        (),
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000024",
        created_at=NOW,
    )

    assert result.requirements == ()
    assert result.document_ids == ()
    assert result.artifact.input_artifacts == ()
