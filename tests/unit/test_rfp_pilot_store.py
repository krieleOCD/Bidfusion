"""Local pilot store tests: private runtime artifacts, no raw prompts.

Pilot outputs from anonymized real RFPs are real business data: they
live only under the gitignored ``runtime/`` area with owner-only file
modes, contain validated/comparison/evaluation records (never raw
prompts or raw model responses), and evaluations are append-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bidfusion.rfp_api_pilot.comparison import (
    NormalizationAgreement,
    RequirementNormalizationComparison,
)
from bidfusion.rfp_api_pilot.evaluation import RequirementNormalizationEvaluation
from bidfusion.rfp_api_pilot.golden_paths import GoldenMatchComparison
from bidfusion.rfp_api_pilot.metrics import PilotRunMetrics
from bidfusion.rfp_api_pilot.prompt import SYSTEM_INSTRUCTIONS
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizedRequirement,
)
from bidfusion.rfp_api_pilot.store import (
    PilotRequirementRecord,
    PilotRunSummaryRecord,
    PilotStoreConflictError,
    RfpApiPilotStore,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260821-0001"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def record_for(requirement_id: str = "REQ-000001") -> PilotRequirementRecord:
    return PilotRequirementRecord(
        bid_id=BID_ID,
        run_id=RUN_ID,
        requirement_id=requirement_id,
        requirement_text="The service shall support Microsoft Sentinel monitoring 24/7.",
        llm=LlmNormalizedRequirement.model_validate(
            {
                "bid_id": BID_ID,
                "requirement_id": requirement_id,
                "operation": "rfp_requirement_normalization",
                "prompt_version": "1",
                "validation_status": "GATEWAY_FAILED",
                "gateway_error_code": "timeout",
                "normalized_at": NOW,
                "requirement_text_sha256": "b" * 64,
            }
        ),
        normalization_comparison=RequirementNormalizationComparison.model_validate(
            {
                "requirement_id": requirement_id,
                "deterministic_technology": "microsoft_sentinel",
                "deterministic_capabilities": [],
                "deterministic_negated": False,
                "agreement": NormalizationAgreement.NOT_EVALUATED,
                "flags": ["LLM_RESULT_MISSING"],
            }
        ),
        golden_comparison=GoldenMatchComparison.model_validate(
            {
                "requirement_id": requirement_id,
                "deterministic": {"match_status": "UNKNOWN", "evidence_count": 0},
            }
        ),
    )


def summary_for() -> PilotRunSummaryRecord:
    return PilotRunSummaryRecord(
        bid_id=BID_ID,
        run_id=RUN_ID,
        created_at=NOW,
        metrics=PilotRunMetrics(
            requirements_total=1,
            requirements_llm_attempted=1,
            llm_valid=0,
            llm_failed=1,
            normalization_agree=0,
            normalization_partial=0,
            normalization_disagree=0,
            deterministic_unknown=0,
            llm_unknown=0,
            golden_match_agree=0,
            human_evaluation_pending=1,
        ),
    )


def evaluation_for(requirement_id: str = "REQ-000001") -> RequirementNormalizationEvaluation:
    return RequirementNormalizationEvaluation.model_validate(
        {
            "requirement_id": requirement_id,
            "evaluated_method": "LLM",
            "evaluation": "UNCLEAR",
            "reviewer": "g.kriele",
            "evaluated_at": NOW,
        }
    )


def test_requirement_records_round_trip_in_sorted_order(tmp_path: Path) -> None:
    store = RfpApiPilotStore(tmp_path / "pilot")
    store.write_requirement_record(record_for("REQ-000002"))
    store.write_requirement_record(record_for("REQ-000001"))

    records = store.read_requirement_records(RUN_ID)
    assert [record.requirement_id for record in records] == ["REQ-000001", "REQ-000002"]
    assert records[0] == record_for("REQ-000001")


def test_summary_round_trips_with_pilot_labels(tmp_path: Path) -> None:
    store = RfpApiPilotStore(tmp_path / "pilot")
    store.write_summary(summary_for())

    loaded = store.read_summary(RUN_ID)
    assert loaded == summary_for()
    assert loaded is not None
    assert loaded.artifact_label == "PILOT_EVALUATION"
    assert "NOT A COMPLIANCE DECISION" in loaded.governance_labels


def test_store_files_and_directories_are_owner_only(tmp_path: Path) -> None:
    root = tmp_path / "pilot"
    store = RfpApiPilotStore(root)
    store.write_requirement_record(record_for())

    assert root.stat().st_mode & 0o777 == 0o700
    record_file = root / RUN_ID / "requirements" / "REQ-000001.json"
    assert record_file.is_file()
    assert record_file.stat().st_mode & 0o777 == 0o600


def test_stored_records_contain_no_prompt_text(tmp_path: Path) -> None:
    store = RfpApiPilotStore(tmp_path / "pilot")
    store.write_requirement_record(record_for())
    content = (tmp_path / "pilot" / RUN_ID / "requirements" / "REQ-000001.json").read_text()
    assert SYSTEM_INSTRUCTIONS[:40] not in content


def test_evaluations_are_append_only(tmp_path: Path) -> None:
    store = RfpApiPilotStore(tmp_path / "pilot")
    store.append_evaluation(RUN_ID, evaluation_for())
    with pytest.raises(PilotStoreConflictError):
        store.append_evaluation(RUN_ID, evaluation_for())

    evaluations = store.read_evaluations(RUN_ID)
    assert len(evaluations) == 1
    assert evaluations[0] == evaluation_for()


def test_default_root_is_the_gitignored_runtime_area() -> None:
    root = RfpApiPilotStore.default_root()
    assert root.parts[-2:] == ("runtime", "rfp_api_pilot")
    gitignore = root.parents[1] / ".gitignore"
    assert "runtime/" in gitignore.read_text(encoding="utf-8")
