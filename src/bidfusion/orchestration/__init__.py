"""Pipeline orchestration: states, tasks, dependencies, retries,
failure handling, human review and resume. Contains no business
logic. Pipeline steps are designed to be idempotent."""

from bidfusion.orchestration.local_pipeline import (
    PIPELINE_NAME,
    PIPELINE_VERSION,
    DocumentRunState,
    PipelineRunSummary,
    StageOutcome,
    run_package,
    verify_run_integrity,
)
from bidfusion.orchestration.projection import run_independent_projection

__all__ = [
    "PIPELINE_NAME",
    "PIPELINE_VERSION",
    "DocumentRunState",
    "PipelineRunSummary",
    "StageOutcome",
    "run_independent_projection",
    "run_package",
    "verify_run_integrity",
]
