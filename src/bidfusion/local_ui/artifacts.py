"""Safe read access to run artifacts: static allowlist plus integrity check.

Downloads and detail views read only fixed, well-known artifact files
below one run directory. Before any read, the run's integrity manifest
is re-verified via the pipeline's own
:func:`bidfusion.orchestration.verify_run_integrity`; any deviation
refuses access with a static operator-safe message. The download
allowlist deliberately excludes canonical and extraction payloads —
the UI serves the human-facing packages and the gate/summary records
only, without creating new data copies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from bidfusion.orchestration import verify_run_integrity
from bidfusion.quality import ReviewPackage
from bidfusion.schemas import RequirementExtractionResult, WorkingPackage
from bidfusion.schemas.normalization import NormalizedBidDataset

#: Static download allowlist: UI artifact name -> (relative path, mimetype).
DOWNLOADABLE_ARTIFACTS: Final[dict[str, tuple[str, str]]] = {
    "working-package.json": (
        "working-package/working-package.payload.json",
        "application/json",
    ),
    "working-package.md": ("working-package/working-package.md", "text/markdown"),
    "review-package.json": ("review-package/review-package.json", "application/json"),
    "review-package.md": ("review-package/review-package.md", "text/markdown"),
    "run-summary.json": ("run-summary.json", "application/json"),
    "quality-gate.json": ("quality/quality-gate.json", "application/json"),
    "package-gate.json": ("security/package-gate.json", "application/json"),
}

INTEGRITY_MESSAGE: Final = (
    "The recorded artifacts of this run failed the integrity re-check. "
    "Access is refused; inspect the local run directory manually."
)

_WORKING_PACKAGE_AUDIT = "working-package/working-package.audit.json"
_REQUIREMENTS_AUDIT = "extraction/requirement-extraction.audit.json"
_DATASET_AUDIT = "normalized/normalized-bid-dataset.audit.json"
_REVIEW_PACKAGE = "review-package/review-package.json"


class ArtifactAccessError(RuntimeError):
    """Access to run artifacts was refused; the message is static."""


def require_intact(run_directory: Path) -> None:
    """Fail closed when the run's integrity manifest does not verify."""
    if verify_run_integrity(run_directory):
        raise ArtifactAccessError(INTEGRITY_MESSAGE)


def artifact_file(run_directory: Path, name: str) -> tuple[Path, str] | None:
    """Resolve one allowlisted artifact name to a verified file path.

    Unknown names and files outside the run directory yield ``None``;
    a failing integrity re-check raises :class:`ArtifactAccessError`.
    """
    entry = DOWNLOADABLE_ARTIFACTS.get(name)
    if entry is None:
        return None
    relative, mimetype = entry
    root = run_directory.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    require_intact(run_directory)
    return path, mimetype


def read_text_artifact(run_directory: Path, name: str) -> str | None:
    """UTF-8 content of one allowlisted artifact, after integrity check."""
    located = artifact_file(run_directory, name)
    if located is None:
        return None
    path, _ = located
    return path.read_text(encoding="utf-8")


def load_working_package(
    run_directory: Path,
) -> tuple[WorkingPackage, RequirementExtractionResult, NormalizedBidDataset]:
    """Validated working-package models for the structured view."""
    require_intact(run_directory)
    return (
        WorkingPackage.model_validate(_read_json(run_directory, _WORKING_PACKAGE_AUDIT)),
        RequirementExtractionResult.model_validate(_read_json(run_directory, _REQUIREMENTS_AUDIT)),
        _validate_dataset(_read_json(run_directory, _DATASET_AUDIT)),
    )


def _validate_dataset(payload: object) -> NormalizedBidDataset:
    """Validate the dataset dump.

    The audit dump serializes the computed ``completeness.state``;
    the strict schema forbids unknown input fields and recomputes the
    state from the stream fields, so the serialized copy is dropped
    before validation instead of weakening the schema.
    """
    if isinstance(payload, dict):
        completeness = payload.get("completeness")
        if isinstance(completeness, dict):
            completeness.pop("state", None)
    return NormalizedBidDataset.model_validate(payload)


def load_requirements(run_directory: Path) -> RequirementExtractionResult:
    """Validated requirement extraction result, after integrity check."""
    require_intact(run_directory)
    return RequirementExtractionResult.model_validate(
        _read_json(run_directory, _REQUIREMENTS_AUDIT)
    )


def load_review_package(run_directory: Path) -> ReviewPackage:
    """Validated review-package model for the structured view."""
    require_intact(run_directory)
    return ReviewPackage.model_validate(_read_json(run_directory, _REVIEW_PACKAGE))


def _read_json(run_directory: Path, relative: str) -> object:
    return json.loads((run_directory / relative).read_text(encoding="utf-8"))
