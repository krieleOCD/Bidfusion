"""Metadata-only pilot metrics. Counts, never quality claims.

Without ground-truth labels there is no accuracy, precision, recall, or
success rate to report — only outcome counts. The printed summary
carries the pilot governance labels and never any requirement text.
"""

from __future__ import annotations

from collections import Counter

from pydantic import Field, model_validator

from bidfusion.rfp_api_pilot.comparison import NormalizationAgreement
from bidfusion.schemas.common import BidfusionModel

GOVERNANCE_LABELS = (
    "ANONYMIZED REAL RFP PILOT",
    "ORANGE PROXY",
    "MACHINE NORMALIZATION",
    "HUMAN EVALUATION REQUIRED",
    "NOT A COMPLIANCE DECISION",
)


class PilotRunMetrics(BidfusionModel):
    """Counters for one pilot run; every value is a non-negative count."""

    requirements_total: int = Field(ge=0)
    requirements_llm_attempted: int = Field(ge=0)
    llm_valid: int = Field(ge=0)
    llm_failed: int = Field(ge=0)
    normalization_agree: int = Field(ge=0)
    normalization_partial: int = Field(ge=0)
    normalization_disagree: int = Field(ge=0)
    deterministic_unknown: int = Field(ge=0)
    llm_unknown: int = Field(ge=0)
    golden_match_agree: int = Field(ge=0)
    human_evaluation_pending: int = Field(ge=0)

    @model_validator(mode="after")
    def _attempts_add_up(self) -> PilotRunMetrics:
        if self.requirements_llm_attempted != self.llm_valid + self.llm_failed:
            msg = "requirements_llm_attempted must equal llm_valid + llm_failed"
            raise ValueError(msg)
        return self

    @classmethod
    def from_counts(
        cls,
        *,
        requirements_total: int,
        llm_valid: int,
        llm_failed: int,
        agreements: tuple[NormalizationAgreement, ...],
        golden_match_agree: int,
        human_evaluation_pending: int,
    ) -> PilotRunMetrics:
        """Fold per-requirement agreement statuses into run counters."""
        counted = Counter(agreements)
        return cls(
            requirements_total=requirements_total,
            requirements_llm_attempted=llm_valid + llm_failed,
            llm_valid=llm_valid,
            llm_failed=llm_failed,
            normalization_agree=counted[NormalizationAgreement.AGREE],
            normalization_partial=counted[NormalizationAgreement.PARTIAL_AGREEMENT],
            normalization_disagree=counted[NormalizationAgreement.DISAGREE],
            deterministic_unknown=counted[NormalizationAgreement.DETERMINISTIC_UNKNOWN],
            llm_unknown=counted[NormalizationAgreement.LLM_UNKNOWN],
            golden_match_agree=golden_match_agree,
            human_evaluation_pending=human_evaluation_pending,
        )


def format_summary(metrics: PilotRunMetrics) -> str:
    """Operator summary: governance labels plus counts. No document content."""
    lines = [
        " | ".join(GOVERNANCE_LABELS),
        f"Requirements extracted: {metrics.requirements_total}",
        f"Sent to LLM: {metrics.requirements_llm_attempted}",
        f"Valid LLM results: {metrics.llm_valid}",
        f"LLM failures: {metrics.llm_failed}",
        f"Normalization agreements: {metrics.normalization_agree}",
        f"Partial agreements: {metrics.normalization_partial}",
        f"Disagreements: {metrics.normalization_disagree}",
        f"Deterministic unknown: {metrics.deterministic_unknown}",
        f"LLM unknown: {metrics.llm_unknown}",
        f"Golden match agreements: {metrics.golden_match_agree}",
        f"Human evaluation required: {metrics.human_evaluation_pending}",
    ]
    return "\n".join(lines)
