"""Tests for the working-package builder and Markdown renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.normalization import merge_extractions
from bidfusion.quality import ParsedDocumentQuality, evaluate_quality
from bidfusion.schemas import (
    CanonicalDocument,
    DeadlineExtractionResult,
    DeadlineKind,
    FormalityExtractionResult,
    NormalizedBidDataset,
    Requirement,
    RequirementExtractionResult,
    RequirementModality,
    WorkingPackage,
)
from bidfusion.working_package import build_working_package, render_markdown

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def build_package(
    canonicals: tuple[CanonicalDocument, ...],
) -> tuple[
    WorkingPackage,
    NormalizedBidDataset,
    RequirementExtractionResult,
    DeadlineExtractionResult,
    FormalityExtractionResult,
]:
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000021",
        created_at=NOW,
    )
    deadlines = extract_deadlines(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000022",
        created_at=NOW,
    )
    formalities = extract_formalities(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000023",
        created_at=NOW,
    )
    dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000024",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    package = build_working_package(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        quality=quality,
        artifact_id="ART-20260804-000025",
        generated_at=NOW,
    )
    return package, dataset, requirements, deadlines, formalities


def normalized_requirements(
    dataset: NormalizedBidDataset,
    requirements: RequirementExtractionResult,
) -> tuple[Requirement, ...]:
    by_id = {item.requirement_id: item for item in requirements.requirements}
    return tuple(by_id[reference.object_id] for reference in dataset.requirements)


def test_working_package_summary_counts_and_critical_requirements(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    package, dataset, _, _, _ = build_package(rfp_minimal_canonicals)

    assert package.bid_id == BID_ID
    assert package.source_dataset == dataset.artifact.as_reference()
    summary = package.requirements_summary
    # v0.2 also captures the two label-free submission rows of the
    # formalities sheet (both MUST), on top of the eight v0.1 records.
    assert summary.total == 10
    assert summary.by_modality[RequirementModality.MUST] == 6
    assert summary.by_modality[RequirementModality.UNKNOWN] == 1
    assert sum(summary.by_modality.values()) == summary.total
    assert sum(summary.by_category.values()) == summary.total
    assert package.critical_requirements == (
        "REQ-000001",
        "REQ-000002",
        "REQ-000006",
        "REQ-000009",
        # the two label-free MUST submission rows captured by v0.2
        "REQ-000010",
        "REQ-000011",
    )


def test_working_package_timeline_is_sorted_and_bid_isolated(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    package, _, _, _, _ = build_package(rfp_minimal_canonicals)

    assert [deadline.kind for deadline in package.timeline] == [
        DeadlineKind.OTHER,
        DeadlineKind.QA,
        DeadlineKind.SUBMISSION,
        DeadlineKind.PRESENTATION,
        DeadlineKind.CONTRACT_START,
    ]
    assert [deadline.due_at for deadline in package.timeline] == sorted(
        deadline.due_at for deadline in package.timeline
    )


def test_working_package_links_statements_to_normalized_objects_and_sources(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    package, _, _, _, _ = build_package(rfp_minimal_canonicals)

    instructions = package.submission_instructions
    assert instructions.portal is not None
    assert instructions.portal.normalized_object_ids == ("FORM-001",)
    assert len(instructions.formats) == 3
    assert len(instructions.signatures_required) == 1
    assert len(instructions.upload_process) == 1
    for statement in (
        instructions.portal,
        *instructions.formats,
        *instructions.signatures_required,
        *instructions.upload_process,
    ):
        assert statement.sources, "every statement must carry evidence"

    assert len(package.open_questions) == 1
    question = package.open_questions[0]
    assert question.potential_clarification
    assert question.statement.normalized_object_ids == ("REQ-000005",)


def build_chain_without_package(
    canonicals: tuple[CanonicalDocument, ...],
) -> tuple[
    NormalizedBidDataset,
    RequirementExtractionResult,
    DeadlineExtractionResult,
    FormalityExtractionResult,
]:
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000031",
        created_at=NOW,
    )
    deadlines = extract_deadlines(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000032",
        created_at=NOW,
    )
    formalities = extract_formalities(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000033",
        created_at=NOW,
    )
    dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000034",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    return dataset, requirements, deadlines, formalities


def test_builder_refuses_review_required_reports_from_parser_warnings(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities = build_chain_without_package(
        rfp_minimal_canonicals
    )
    quality = evaluate_quality(
        parsed=(
            ParsedDocumentQuality(
                document_id="DOC-001",
                filename="rfp-invitation.pdf",
                warnings=("page 2 contains no extractable text",),
            ),
        ),
        unprocessed=(),
        canonicals=rfp_minimal_canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )

    assert quality.status.value == "REVIEW_REQUIRED"
    with pytest.raises(ValueError, match="ACCEPTABLE"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000035",
            generated_at=NOW,
        )


def test_builder_refuses_unresolved_conflicts_and_low_coverage(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities = build_chain_without_package(
        rfp_quality_canonicals
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=rfp_quality_canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )

    assert dataset.unresolved_conflicts, "fixture must carry a conflict"
    assert quality.status.value == "REVIEW_REQUIRED"
    with pytest.raises(ValueError, match="ACCEPTABLE"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000036",
            generated_at=NOW,
        )


def test_builder_refuses_reports_from_a_different_run_dataset_or_bid(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities = build_chain_without_package(
        rfp_minimal_canonicals
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=rfp_minimal_canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    assert quality.status.value == "ACCEPTABLE"

    foreign_dataset_reference = quality.dataset_artifact.model_copy(
        update={"artifact_id": "ART-20260804-999999"}
    )
    for update, message in (
        ({"run_id": "RUN-20260805-0002"}, "run"),
        ({"dataset_artifact": foreign_dataset_reference}, "dataset"),
        ({"bid_id": "BID-2026-000999"}, "bid"),
    ):
        with pytest.raises(ValueError, match=message):
            build_working_package(
                dataset,
                requirements=requirements,
                deadlines=deadlines,
                formalities=formalities,
                quality=quality.model_copy(update=update),
                artifact_id="ART-20260804-000037",
                generated_at=NOW,
            )


def _acceptable_chain(
    canonicals: tuple[CanonicalDocument, ...],
) -> tuple[
    NormalizedBidDataset,
    RequirementExtractionResult,
    DeadlineExtractionResult,
    FormalityExtractionResult,
    Any,
]:
    dataset, requirements, deadlines, formalities = build_chain_without_package(canonicals)
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    assert quality.status.value == "ACCEPTABLE"
    return dataset, requirements, deadlines, formalities, quality


def test_builder_refuses_extraction_results_from_another_run(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, _, deadlines, formalities, quality = _acceptable_chain(rfp_minimal_canonicals)
    foreign_requirements = extract_requirements(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id="RUN-20260805-0002",
        artifact_id="ART-20260805-000031",
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="not the one"):
        build_working_package(
            dataset,
            requirements=foreign_requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000038",
            generated_at=NOW,
        )


def test_builder_refuses_same_id_but_different_content_hash(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    # Same artifact ID, same run — but re-sealed at a different time, so the
    # content hash differs from what the gate evaluated.
    resealed = extract_requirements(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id=requirements.artifact.artifact_id,
        created_at=NOW.replace(hour=13),
    )
    assert resealed.artifact.artifact_id == requirements.artifact.artifact_id
    assert resealed.artifact.content_hash != requirements.artifact.content_hash

    with pytest.raises(ValueError, match="not the one"):
        build_working_package(
            dataset,
            requirements=resealed,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000039",
            generated_at=NOW,
        )


def test_builder_refuses_swapped_stream_artifacts_in_the_report(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    swapped = quality.model_copy(
        update={
            "deadline_artifact": quality.formality_artifact,
            "formality_artifact": quality.deadline_artifact,
        }
    )

    with pytest.raises(ValueError, match="not the one"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=swapped,
            artifact_id="ART-20260804-000040",
            generated_at=NOW,
        )


def test_builder_refuses_a_report_that_evaluated_a_different_artifact_set(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    # The report claims no formality stream was evaluated ("additional
    # foreign stream" from the builder's perspective).
    without_formalities = quality.model_copy(update={"formality_artifact": None})

    with pytest.raises(ValueError, match="not the one"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=without_formalities,
            artifact_id="ART-20260804-000041",
            generated_at=NOW,
        )


def test_builder_refuses_a_dataset_whose_input_lineage_does_not_match(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    # A dataset whose input lineage lacks the formality artifact the gate
    # evaluated — even when a tampered report is bound to exactly that
    # dataset, the lineage cross-check refuses to build.
    lineage_mismatch = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id=dataset.artifact.artifact_id,
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=None,
    )
    tampered_quality = quality.model_copy(
        update={"dataset_artifact": lineage_mismatch.artifact.as_reference()}
    )

    with pytest.raises(ValueError, match="input lineage"):
        build_working_package(
            lineage_mismatch,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=tampered_quality,
            artifact_id="ART-20260804-000042",
            generated_at=NOW,
        )


FOREIGN_RUN_ID = "RUN-20260805-0002"


def _foreign_extraction(
    canonicals: tuple[CanonicalDocument, ...],
    *,
    foreign_requirements: bool,
    foreign_deadlines: bool,
    foreign_formalities: bool,
) -> tuple[RequirementExtractionResult, DeadlineExtractionResult, FormalityExtractionResult]:
    """Extraction results where selected streams belong to a foreign run."""
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=FOREIGN_RUN_ID if foreign_requirements else RUN_ID,
        artifact_id="ART-20260805-000031" if foreign_requirements else "ART-20260804-000031",
        created_at=NOW,
    )
    deadlines = extract_deadlines(
        canonicals,
        bid_id=BID_ID,
        run_id=FOREIGN_RUN_ID if foreign_deadlines else RUN_ID,
        artifact_id="ART-20260805-000032" if foreign_deadlines else "ART-20260804-000032",
        created_at=NOW,
    )
    formalities = extract_formalities(
        canonicals,
        bid_id=BID_ID,
        run_id=FOREIGN_RUN_ID if foreign_formalities else RUN_ID,
        artifact_id="ART-20260805-000033" if foreign_formalities else "ART-20260804-000033",
        created_at=NOW,
    )
    return requirements, deadlines, formalities


def _evaluated(
    canonicals: tuple[CanonicalDocument, ...],
    requirements: RequirementExtractionResult,
    deadlines: DeadlineExtractionResult,
    formalities: FormalityExtractionResult,
) -> tuple[NormalizedBidDataset, Any]:
    dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000034",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    return dataset, quality


def test_builder_refuses_all_extraction_artifacts_from_a_foreign_run(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    """Consistently referenced foreign-run artifacts must still be rejected."""
    requirements, deadlines, formalities = _foreign_extraction(
        rfp_minimal_canonicals,
        foreign_requirements=True,
        foreign_deadlines=True,
        foreign_formalities=True,
    )
    dataset, quality = _evaluated(rfp_minimal_canonicals, requirements, deadlines, formalities)
    # Report and dataset reference the foreign artifacts consistently.
    assert quality.status.value == "ACCEPTABLE"
    assert quality.requirement_artifact is not None
    assert quality.requirement_artifact.run_id == FOREIGN_RUN_ID

    with pytest.raises(ValueError, match="foreign run"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000043",
            generated_at=NOW,
        )


def test_builder_refuses_a_single_foreign_run_extraction_artifact(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, deadlines, formalities = _foreign_extraction(
        rfp_minimal_canonicals,
        foreign_requirements=False,
        foreign_deadlines=False,
        foreign_formalities=True,
    )
    dataset, quality = _evaluated(rfp_minimal_canonicals, requirements, deadlines, formalities)
    assert quality.status.value == "ACCEPTABLE"

    with pytest.raises(ValueError, match="foreign run"):
        build_working_package(
            dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000044",
            generated_at=NOW,
        )


def test_builder_refuses_a_same_id_dataset_with_altered_content(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    """The demonstrated bypass: same ID and hash, mutated dataset fields."""
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    stripped = dataset.model_copy(update={"requirements": ()})
    assert stripped.artifact.as_reference() == dataset.artifact.as_reference()

    with pytest.raises(ValueError, match="content hash"):
        build_working_package(
            stripped,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000045",
            generated_at=NOW,
        )


def test_builder_refuses_a_same_id_dataset_with_a_different_hash(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    # Re-sealed requirement stream (same IDs, different timestamps) changes
    # the dataset payload and thereby its hash while the ID stays the same.
    resealed_requirements = extract_requirements(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id=requirements.artifact.artifact_id,
        created_at=NOW.replace(hour=13),
    )
    altered_dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id=dataset.artifact.artifact_id,
        created_at=NOW,
        requirements=resealed_requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    assert altered_dataset.artifact.artifact_id == dataset.artifact.artifact_id
    assert altered_dataset.artifact.content_hash != dataset.artifact.content_hash

    with pytest.raises(ValueError, match="normalized dataset is not the one"):
        build_working_package(
            altered_dataset,
            requirements=resealed_requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000046",
            generated_at=NOW,
        )


def test_builder_refuses_a_same_id_same_hash_dataset_from_the_wrong_run(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )
    wrong_run_dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=FOREIGN_RUN_ID,
        artifact_id=dataset.artifact.artifact_id,
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    # The payload carries no run ID, so ID and hash are identical — only
    # the envelope run differs.
    assert wrong_run_dataset.artifact.content_hash == dataset.artifact.content_hash

    with pytest.raises(ValueError, match="run"):
        build_working_package(
            wrong_run_dataset,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            quality=quality,
            artifact_id="ART-20260804-000047",
            generated_at=NOW,
        )


def test_builder_succeeds_with_exact_report_dataset_and_extraction_lineage(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset, requirements, deadlines, formalities, quality = _acceptable_chain(
        rfp_minimal_canonicals
    )

    package = build_working_package(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        quality=quality,
        artifact_id="ART-20260804-000048",
        generated_at=NOW,
    )

    assert package.requirements_summary.total == 10
    assert package.source_dataset == dataset.artifact.as_reference()


def test_unchecked_builder_is_not_publicly_exported() -> None:
    import bidfusion.working_package as public_api

    assert "build_working_package" in public_api.__all__
    assert not any(name.endswith("unchecked") for name in public_api.__all__)
    assert not hasattr(public_api, "_build_working_package_unchecked")


def test_markdown_rendering_is_deterministic_and_readable(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    package, dataset, requirements, _, _ = build_package(rfp_minimal_canonicals)
    items = normalized_requirements(dataset, requirements)

    first = render_markdown(package, requirements=items, completeness=dataset.completeness)
    second = render_markdown(package, requirements=items, completeness=dataset.completeness)

    assert first == second
    assert f"# Bid Working Package — {BID_ID}" in first
    assert "COMPLETE (3/3 streams completed)" in first
    assert "| 2026-09-30 17:00 | SUBMISSION |" in first
    assert "REQ-000005" in first
    assert "requirements-matrix.xlsx (Requirements!B2)" in first
    assert "rfp-invitation.pdf (p. 2)" in first
    assert "None" not in first
