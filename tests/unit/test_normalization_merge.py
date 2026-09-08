"""Tests for the deterministic normalization fan-in."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.normalization.merge import merge_extractions
from bidfusion.schemas import (
    CanonicalDocument,
    ExtractionCompletenessState,
    ExtractionStream,
    NormalizedBidDataset,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def merged_dataset(
    canonicals: tuple[CanonicalDocument, ...],
    *,
    with_formalities: bool = True,
) -> NormalizedBidDataset:
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
    formalities = (
        extract_formalities(
            canonicals,
            bid_id=BID_ID,
            run_id=RUN_ID,
            artifact_id="ART-20260804-000023",
            created_at=NOW,
        )
        if with_formalities
        else None
    )
    return merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000024",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        failed_streams=() if with_formalities else (ExtractionStream.FORMALITY,),
    )


def test_merge_deduplicates_exact_duplicates_and_keeps_all_sources(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset = merged_dataset(rfp_minimal_canonicals)

    # 15 extracted in v0.3 (nine v0.1 records plus six label-free
    # detections), one agreeing duplicate merged
    assert len(dataset.requirements) == 14
    merged_requirement = next(
        reference for reference in dataset.requirements if len(reference.sources) == 2
    )
    assert merged_requirement.object_id == "REQ-000002"
    source_locators = {
        source.locator.cell_id or f"page-{source.locator.page}"
        for source in merged_requirement.sources
    }
    assert source_locators == {"page-2", "Requirements!B4"}

    assert len(dataset.deadlines) == 5  # all deadlines are unique in the clean fixture
    assert dataset.unresolved_conflicts == ()

    assert len(dataset.formalities) == 6
    assert dataset.completeness.state is ExtractionCompletenessState.COMPLETE
    assert len(dataset.artifact.input_artifacts) == 3


def test_merge_preserves_conflicting_duplicates_instead_of_swallowing_them(
    rfp_quality_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset = merged_dataset(rfp_quality_canonicals)

    # The quality fixture repeats one requirement text with a conflicting
    # modality (SHOULD in the PDF, MUST in the XLSX modality column).
    assert len(dataset.unresolved_conflicts) == 1
    conflict = dataset.unresolved_conflicts[0]
    assert "conflicting modality/category" in conflict.description
    assert len(conflict.object_ids) == 2
    conflicting_ids = set(conflict.object_ids)
    separate_refs = [
        reference for reference in dataset.requirements if reference.object_id in conflicting_ids
    ]
    assert len(separate_refs) == 2, "conflicting duplicates must stay separate objects"


def test_merge_records_failed_streams_instead_of_hiding_them(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset = merged_dataset(rfp_minimal_canonicals, with_formalities=False)

    assert dataset.formalities == ()
    assert dataset.completeness.state is ExtractionCompletenessState.FAILED
    assert dataset.completeness.failed_streams == (ExtractionStream.FORMALITY,)
    assert len(dataset.artifact.input_artifacts) == 2


def test_merge_is_deterministic(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    first = merged_dataset(rfp_minimal_canonicals)
    second = merged_dataset(rfp_minimal_canonicals)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.artifact.content_hash == second.artifact.content_hash


def test_merge_rejects_contradictory_stream_accounting(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    formalities = extract_formalities(
        rfp_minimal_canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000023",
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="both completed and failed"):
        merge_extractions(
            bid_id=BID_ID,
            run_id=RUN_ID,
            artifact_id="ART-20260804-000024",
            created_at=NOW,
            requirements=None,
            deadlines=None,
            formalities=formalities,
            failed_streams=(ExtractionStream.FORMALITY,),
        )
