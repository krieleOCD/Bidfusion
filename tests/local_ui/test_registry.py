"""Unit tests for the in-memory run registry (session navigation only).

The registry is a thin lookup table for this UI process; the run
artifacts on disk stay the authoritative truth about every run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bidfusion.local_ui.registry import RunRegistry
from bidfusion.orchestration import PipelineRunSummary, run_package

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "synthetic"
BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


def _security_only_summary(tmp_path: Path) -> PipelineRunSummary:
    return run_package(
        input_dir=FIXTURES / "rfp-blocked",
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=False,
        now=NOW,
    )


def test_registry_assigns_sequential_keys_and_lists_newest_first(tmp_path: Path) -> None:
    summary = _security_only_summary(tmp_path)
    registry = RunRegistry()

    first = registry.add(
        package_name="rfp-blocked",
        requested_processing=False,
        summary=summary,
        output_root=tmp_path / "out",
    )
    second = registry.add(
        package_name="rfp-blocked",
        requested_processing=False,
        summary=summary,
        output_root=tmp_path / "out",
    )

    assert first.key == "run-001"
    assert second.key == "run-002"
    assert registry.get("run-001") == first
    assert registry.get("run-002") == second
    assert registry.all() == (second, first)


def test_registry_returns_none_for_unknown_keys(tmp_path: Path) -> None:
    summary = _security_only_summary(tmp_path)
    registry = RunRegistry()
    registry.add(
        package_name="rfp-blocked",
        requested_processing=False,
        summary=summary,
        output_root=tmp_path / "out",
    )

    assert registry.get("run-999") is None
    assert registry.get("../run-001") is None
    assert registry.get("") is None
