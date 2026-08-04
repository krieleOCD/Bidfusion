"""Deterministic run-scoped identifier allocation for the local pipeline."""

from __future__ import annotations

import re
from datetime import datetime

#: Strict allowlist for operator-supplied bid identifiers. Matches the
#: ``BidId`` schema pattern; anything else must never reach the filesystem.
_BID_ID_ALLOWLIST = re.compile(r"^BID-\d{4}-\d{6}$")


def validate_bid_id(bid_id: str) -> str:
    """Validate an operator-supplied bid ID before any filesystem use.

    Rejects absolute paths, path separators, ``.``/``..``, and everything
    outside the strict ``BID-YYYY-NNNNNN`` allowlist. Returns the validated
    value so callers can use the checked identifier explicitly.
    """
    if not bid_id or bid_id in {".", ".."}:
        msg = "bid ID must not be empty or a relative path component"
        raise ValueError(msg)
    if bid_id.startswith(("/", "\\")) or ":" in bid_id:
        msg = "bid ID must not be an absolute path"
        raise ValueError(msg)
    if "/" in bid_id or "\\" in bid_id:
        msg = "bid ID must not contain path separators"
        raise ValueError(msg)
    if not _BID_ID_ALLOWLIST.fullmatch(bid_id):
        msg = "bid ID must match the BID-YYYY-NNNNNN format"
        raise ValueError(msg)
    return bid_id


def run_id_for(started_at: datetime) -> str:
    """Build the ``RUN-YYYYMMDD-HHMMSSffffff`` identifier used by local runs."""
    return started_at.strftime("RUN-%Y%m%d-%H%M%S%f")


def document_id_for(index: int) -> str:
    """Build the sequential ``DOC-NNN`` identifier for a registered document."""
    if index < 1:
        msg = "document indexes start at 1"
        raise ValueError(msg)
    return f"DOC-{index:03d}"


class ArtifactIdAllocator:
    """Allocate unique, deterministic artifact IDs for one pipeline run.

    All artifact kinds of a run share one counter, so identifiers never
    collide between raw, canonical, extraction, and aggregate artifacts.
    """

    def __init__(self, started_at: datetime) -> None:
        self._prefix = started_at.strftime("ART-%Y%m%d-%H%M%S%f")
        self._next_sequence = 0

    def allocate(self) -> str:
        """Return the next ``ART-YYYYMMDD-<time><seq>`` identifier."""
        self._next_sequence += 1
        if self._next_sequence > 999_999:
            msg = "a local pipeline run supports at most 999999 artifacts"
            raise ValueError(msg)
        return f"{self._prefix}{self._next_sequence:06d}"
