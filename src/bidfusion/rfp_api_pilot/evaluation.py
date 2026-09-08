"""Human pilot evaluation of normalization quality (``PILOT_EVALUATION``).

A lightweight record of which normalization a human found more
appropriate for one requirement. It is pilot measurement data only:

- it never affects golden truth (no import of the golden store, no
  claim promotion);
- it is NOT a production review decision and stays structurally separate
  from :class:`bidfusion.bid_intelligence.review.contracts.RequirementAssessmentReview`;
- the artifact set it belongs to is labeled ``PILOT_EVALUATION``, not a
  golden evaluation set — that name requires human curation that does
  not exist yet.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, model_validator

from bidfusion.schemas.common import BidfusionModel

PILOT_EVALUATION_LABEL: Final = "PILOT_EVALUATION"

MAX_REVIEWER_LENGTH = 120
MAX_NOTE_LENGTH = 2000


class EvaluatedMethod(StrEnum):
    """Which normalization path the human judgement refers to."""

    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"
    BOTH = "BOTH"


class NormalizationEvaluationVerdict(StrEnum):
    """Closed human verdict on normalization quality for one requirement."""

    DETERMINISTIC_BETTER = "DETERMINISTIC_BETTER"
    LLM_BETTER = "LLM_BETTER"
    EQUIVALENT = "EQUIVALENT"
    BOTH_WRONG = "BOTH_WRONG"
    UNCLEAR = "UNCLEAR"


class RequirementNormalizationEvaluation(BidfusionModel):
    """One human evaluation of normalization quality for the pilot."""

    evaluation_label: Literal["PILOT_EVALUATION"] = PILOT_EVALUATION_LABEL
    requirement_id: str = Field(min_length=1)
    evaluated_method: EvaluatedMethod
    evaluation: NormalizationEvaluationVerdict
    reviewer: str = Field(min_length=1, max_length=MAX_REVIEWER_LENGTH)
    evaluated_at: datetime
    note: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_LENGTH)

    @model_validator(mode="after")
    def _record_is_coherent(self) -> RequirementNormalizationEvaluation:
        if self.evaluated_at.tzinfo is None:
            msg = "evaluated_at must be timezone-aware"
            raise ValueError(msg)
        if not self.reviewer.strip():
            msg = "an evaluation requires a named reviewer"
            raise ValueError(msg)
        return self
