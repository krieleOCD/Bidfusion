"""In-memory registry of UI-started pipeline runs (session navigation only).

The registry only powers navigation within one UI process. The run
artifacts on disk — ``run-summary.json``, gate results, packages, and
the integrity manifest — remain the authoritative truth about every
run.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from bidfusion.orchestration import PipelineRunSummary


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One UI-started pipeline run and where its artifacts live."""

    key: str
    package_name: str
    requested_processing: bool
    summary: PipelineRunSummary
    output_root: Path


class RunRegistry:
    """Thread-safe, insertion-ordered store of this session's runs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, RunRecord] = {}
        self._counter = 0

    def add(
        self,
        *,
        package_name: str,
        requested_processing: bool,
        summary: PipelineRunSummary,
        output_root: Path,
    ) -> RunRecord:
        """Store a finished run under a fresh sequential key."""
        with self._lock:
            self._counter += 1
            record = RunRecord(
                key=f"run-{self._counter:03d}",
                package_name=package_name,
                requested_processing=requested_processing,
                summary=summary,
                output_root=output_root,
            )
            self._records[record.key] = record
            return record

    def get(self, key: str) -> RunRecord | None:
        """The record stored under ``key``, or ``None``."""
        with self._lock:
            return self._records.get(key)

    def all(self) -> tuple[RunRecord, ...]:
        """All records, newest first."""
        with self._lock:
            return tuple(reversed(self._records.values()))
