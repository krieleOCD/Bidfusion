"""In-memory registry of UI-started upload attempts (session navigation only).

Deliberately separate from :class:`bidfusion.local_ui.registry.RunRegistry`
(the synthetic-fixture pipeline registry): free uploads and synthetic
demo runs are two distinct flows and must never share navigation state.

The registry stores only an opaque key and the package directory —
never the quarantine result itself. Every view re-reads and re-verifies
the persisted, sealed artifacts from that directory
(:func:`bidfusion.bidrun.quarantine.read_quarantine_package`) before
displaying anything; the registry cannot paper over a tampered package.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UploadRecord:
    """A session-navigation pointer only — not the source of truth."""

    key: str
    package_directory: Path


class UploadRegistry:
    """Thread-safe, insertion-ordered store of this session's uploads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, UploadRecord] = {}
        self._counter = 0

    def add(self, *, package_directory: Path) -> UploadRecord:
        """Store a finished upload under a fresh sequential opaque key."""
        with self._lock:
            self._counter += 1
            record = UploadRecord(
                key=f"upload-{self._counter:03d}",
                package_directory=package_directory,
            )
            self._records[record.key] = record
            return record

    def get(self, key: str) -> UploadRecord | None:
        """The record stored under ``key``, or ``None``."""
        with self._lock:
            return self._records.get(key)

    def all(self) -> tuple[UploadRecord, ...]:
        """All records, newest first."""
        with self._lock:
            return tuple(reversed(self._records.values()))
