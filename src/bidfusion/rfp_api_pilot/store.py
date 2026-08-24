"""Local pilot store: private, gitignored runtime artifacts.

Pilot outputs from anonymized real RFPs are real business data. They are
written only below one owner-only (0700/0600) root — by default the
gitignored ``runtime/rfp_api_pilot`` area of this checkout, mirroring
the golden store convention — and never into fixtures or the repository.

Stored per requirement: the validated normalization wrapper, both
comparison records, and the requirement text (operator-asserted
anonymized; needed for meaningful human evaluation). Never stored: raw
prompts, raw model responses, or reasoning — the wrapper cannot carry
them by construction. Layout below the root:

    <run_id>/requirements/<requirement_id>.json
    <run_id>/evaluations/<requirement_id>-<method>.json   (append-only)
    <run_id>/pilot-summary.json

The artifact set is labeled ``PILOT_EVALUATION`` (Part of the pilot; it
is NOT a golden evaluation set — that name requires human curation).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from bidfusion.rfp_api_pilot.comparison import RequirementNormalizationComparison
from bidfusion.rfp_api_pilot.contracts import MAX_REQUIREMENT_TEXT_CHARS
from bidfusion.rfp_api_pilot.evaluation import (
    PILOT_EVALUATION_LABEL,
    RequirementNormalizationEvaluation,
)
from bidfusion.rfp_api_pilot.golden_paths import GoldenMatchComparison
from bidfusion.rfp_api_pilot.metrics import GOVERNANCE_LABELS, PilotRunMetrics
from bidfusion.rfp_api_pilot.service import LlmNormalizedRequirement
from bidfusion.schemas.common import BidfusionModel, SemanticVersion
from bidfusion.schemas.ids import BidId, RequirementId, RunId
from bidfusion.shared.pathguards import repository_root
from bidfusion.shared.secure_io import ensure_private_directory, write_private_text

PILOT_STORE_SCHEMA_VERSION = "1.0.0"

_REQUIREMENTS_DIR = "requirements"
_EVALUATIONS_DIR = "evaluations"
_SUMMARY_FILENAME = "pilot-summary.json"


class PilotStoreConflictError(RuntimeError):
    """An append-only pilot record already exists; nothing was overwritten."""


class PilotRequirementRecord(BidfusionModel):
    """One requirement's complete pilot record for later human evaluation."""

    schema_version: SemanticVersion = PILOT_STORE_SCHEMA_VERSION
    artifact_label: Literal["PILOT_EVALUATION"] = PILOT_EVALUATION_LABEL
    bid_id: BidId
    run_id: RunId
    requirement_id: RequirementId
    requirement_text: str = Field(min_length=1, max_length=MAX_REQUIREMENT_TEXT_CHARS * 4)
    llm: LlmNormalizedRequirement
    normalization_comparison: RequirementNormalizationComparison
    #: Absent when the golden knowledge snapshot was not available — that
    #: is a store condition, never a capability statement.
    golden_comparison: GoldenMatchComparison | None = None


class PilotRunSummaryRecord(BidfusionModel):
    """Metadata-only run summary with the pilot governance labels."""

    schema_version: SemanticVersion = PILOT_STORE_SCHEMA_VERSION
    artifact_label: Literal["PILOT_EVALUATION"] = PILOT_EVALUATION_LABEL
    governance_labels: tuple[str, ...] = GOVERNANCE_LABELS
    bid_id: BidId
    run_id: RunId
    created_at: datetime
    metrics: PilotRunMetrics

    @model_validator(mode="after")
    def _timestamp_is_aware(self) -> PilotRunSummaryRecord:
        if self.created_at.tzinfo is None:
            msg = "created_at must be timezone-aware"
            raise ValueError(msg)
        return self


class RfpApiPilotStore:
    """Read/write pilot artifacts under one private local root."""

    def __init__(self, root: Path) -> None:
        self._root = root
        ensure_private_directory(root, root=root.parent if root.parent.exists() else None)

    @classmethod
    def default_root(cls) -> Path:
        """The gitignored runtime location inside this checkout."""
        checkout = repository_root()
        if checkout is None:
            msg = "no repository checkout found for the default pilot store root"
            raise RuntimeError(msg)
        return checkout / "runtime" / "rfp_api_pilot"

    @property
    def root(self) -> Path:
        return self._root

    def write_requirement_record(self, record: PilotRequirementRecord) -> None:
        directory = self._root / record.run_id / _REQUIREMENTS_DIR
        ensure_private_directory(directory, root=self._root)
        self._write(directory / f"{record.requirement_id}.json", record.model_dump_json(indent=2))

    def read_requirement_records(self, run_id: str) -> tuple[PilotRequirementRecord, ...]:
        directory = self._root / run_id / _REQUIREMENTS_DIR
        if not directory.is_dir():
            return ()
        return tuple(
            PilotRequirementRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        )

    def write_summary(self, summary: PilotRunSummaryRecord) -> None:
        directory = self._root / summary.run_id
        ensure_private_directory(directory, root=self._root)
        self._write(directory / _SUMMARY_FILENAME, summary.model_dump_json(indent=2))

    def read_summary(self, run_id: str) -> PilotRunSummaryRecord | None:
        path = self._root / run_id / _SUMMARY_FILENAME
        if not path.is_file():
            return None
        return PilotRunSummaryRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def append_evaluation(
        self, run_id: str, evaluation: RequirementNormalizationEvaluation
    ) -> None:
        directory = self._root / run_id / _EVALUATIONS_DIR
        ensure_private_directory(directory, root=self._root)
        path = directory / (f"{evaluation.requirement_id}-{evaluation.evaluated_method.value}.json")
        if path.exists():
            msg = "an evaluation for this requirement and method already exists"
            raise PilotStoreConflictError(msg)
        self._write(path, evaluation.model_dump_json(indent=2))

    def read_evaluations(self, run_id: str) -> tuple[RequirementNormalizationEvaluation, ...]:
        directory = self._root / run_id / _EVALUATIONS_DIR
        if not directory.is_dir():
            return ()
        return tuple(
            RequirementNormalizationEvaluation.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        )

    def _write(self, path: Path, text: str) -> None:
        write_private_text(path, text + "\n", root=self._root)
