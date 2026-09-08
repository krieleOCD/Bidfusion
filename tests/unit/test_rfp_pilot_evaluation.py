"""Evaluation-record tests: human pilot judgement, separate from review.

``RequirementNormalizationEvaluation`` evaluates normalization QUALITY
for the pilot (``PILOT_EVALUATION``). It must never mutate golden truth
and must stay clearly separate from the production
``RequirementAssessmentReview`` decision record.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bidfusion.bid_intelligence.review.contracts import RequirementAssessmentReview
from bidfusion.rfp_api_pilot.evaluation import (
    PILOT_EVALUATION_LABEL,
    EvaluatedMethod,
    NormalizationEvaluationVerdict,
    RequirementNormalizationEvaluation,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def evaluation_for(**overrides: object) -> RequirementNormalizationEvaluation:
    payload: dict[str, object] = {
        "requirement_id": "REQ-000001",
        "evaluated_method": "LLM",
        "evaluation": "LLM_BETTER",
        "reviewer": "g.kriele",
        "evaluated_at": NOW,
    }
    payload.update(overrides)
    return RequirementNormalizationEvaluation.model_validate(payload)


def test_valid_evaluation_carries_the_pilot_label() -> None:
    evaluation = evaluation_for(note="LLM caught the 24/7 condition.")
    assert evaluation.evaluation_label == PILOT_EVALUATION_LABEL == "PILOT_EVALUATION"
    assert evaluation.evaluation is NormalizationEvaluationVerdict.LLM_BETTER
    assert evaluation.evaluated_method is EvaluatedMethod.LLM


def test_verdict_vocabulary_is_closed_and_complete() -> None:
    assert {member.value for member in NormalizationEvaluationVerdict} == {
        "DETERMINISTIC_BETTER",
        "LLM_BETTER",
        "EQUIVALENT",
        "BOTH_WRONG",
        "UNCLEAR",
    }


def test_label_cannot_be_promoted_to_a_golden_evaluation_set() -> None:
    with pytest.raises(ValidationError):
        evaluation_for(evaluation_label="GOLDEN_EVALUATION_SET")


def test_blank_reviewer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        evaluation_for(reviewer="   ")


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        evaluation_for(evaluated_at="2026-08-21T12:00:00")


def test_note_is_bounded() -> None:
    with pytest.raises(ValidationError):
        evaluation_for(note="n" * 2001)


def test_evaluation_is_distinct_from_the_production_review_record() -> None:
    assert not issubclass(RequirementNormalizationEvaluation, RequirementAssessmentReview)
    review_fields = set(RequirementAssessmentReview.model_fields)
    evaluation_fields = set(RequirementNormalizationEvaluation.model_fields)
    # The evaluation has no reviewed-assessment binding and no review decision.
    assert "decision" not in evaluation_fields
    assert "assessment_digest" not in evaluation_fields
    assert "evaluation" not in review_fields
