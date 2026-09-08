"""Metrics tests: metadata-only pilot counters, honest wording.

Metrics count outcomes; without ground-truth labels they must never be
presented as accuracy, precision, recall, or a success rate, and the
summary must carry the pilot governance labels and no requirement text.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bidfusion.rfp_api_pilot.comparison import NormalizationAgreement
from bidfusion.rfp_api_pilot.metrics import PilotRunMetrics, format_summary


def metrics_for(**overrides: int) -> PilotRunMetrics:
    payload = {
        "requirements_total": 34,
        "requirements_llm_attempted": 34,
        "llm_valid": 32,
        "llm_failed": 2,
        "normalization_agree": 21,
        "normalization_partial": 5,
        "normalization_disagree": 6,
        "deterministic_unknown": 3,
        "llm_unknown": 2,
        "golden_match_agree": 25,
        "human_evaluation_pending": 13,
    }
    payload.update(overrides)
    return PilotRunMetrics.model_validate(payload)


def test_attempted_must_equal_valid_plus_failed() -> None:
    with pytest.raises(ValidationError):
        metrics_for(llm_valid=30)


def test_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        metrics_for(llm_failed=-1)


def test_from_agreements_counts_each_agreement_status() -> None:
    metrics = PilotRunMetrics.from_counts(
        requirements_total=4,
        llm_valid=3,
        llm_failed=1,
        agreements=(
            NormalizationAgreement.AGREE,
            NormalizationAgreement.PARTIAL_AGREEMENT,
            NormalizationAgreement.DETERMINISTIC_UNKNOWN,
            NormalizationAgreement.NOT_EVALUATED,
        ),
        golden_match_agree=2,
        human_evaluation_pending=4,
    )
    assert metrics.requirements_llm_attempted == 4
    assert metrics.normalization_agree == 1
    assert metrics.normalization_partial == 1
    assert metrics.normalization_disagree == 0
    assert metrics.deterministic_unknown == 1
    assert metrics.llm_unknown == 0


def test_summary_is_metadata_only_with_governance_labels() -> None:
    summary = format_summary(metrics_for())
    assert "ANONYMIZED REAL RFP PILOT" in summary
    assert "ORANGE PROXY" in summary
    assert "MACHINE NORMALIZATION" in summary
    assert "HUMAN EVALUATION REQUIRED" in summary
    assert "NOT A COMPLIANCE DECISION" in summary
    assert "Requirements extracted: 34" in summary
    assert "Valid LLM results: 32" in summary
    assert "Disagreements: 6" in summary


def test_summary_never_claims_measured_quality() -> None:
    lowered = format_summary(metrics_for()).lower()
    for banned in ("accuracy", "precision", "recall", "success rate", "% correct"):
        assert banned not in lowered
