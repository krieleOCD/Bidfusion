"""Read-only snapshot access to the golden claims for bridge matching.

The one place where the bid-side bridge touches the golden runtime
store, and it only ever reads. Every failure mode of the store becomes a
stable :class:`KnowledgeStoreState` with a static, operator-safe note —
never a raised store internal, never a filesystem path, and never a
capability ``GAP``: an absent or damaged knowledge store says nothing
about capabilities.

The store's own referential integrity validation stays active: a claims
load that cites unresolvable or version-drifted evidence surfaces as
``INTEGRITY_FAILED`` (the store raises
:class:`~bidfusion.golden_dataset.store.GoldenStoreIntegrityError`,
which covers stale evidence), and nothing of that load is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bidfusion.bid_intelligence.matching.contracts import KnowledgeStoreState
from bidfusion.golden_dataset.contracts import CapabilityClaim
from bidfusion.golden_dataset.store import GoldenKnowledgeStore, GoldenStoreIntegrityError

#: Static, content-free notes per store state. Chosen here, not in a
#: template, so every surface reports the same honest sentence.
STORE_NOTES: dict[KnowledgeStoreState, str] = {
    KnowledgeStoreState.AVAILABLE: (
        "Golden knowledge snapshot loaded; every claim is machine-extracted "
        "and requires human review."
    ),
    KnowledgeStoreState.UNAVAILABLE: (
        "No local golden knowledge store is available. Requirements were not "
        "evaluated — this is not a capability gap."
    ),
    KnowledgeStoreState.NO_CLAIMS: (
        "The local golden knowledge store holds no capability claims yet. "
        "Requirements were not evaluated — this is not a capability gap."
    ),
    KnowledgeStoreState.UNREADABLE: (
        "The local golden knowledge store could not be read. Requirements "
        "were not evaluated — this is not a capability gap."
    ),
    KnowledgeStoreState.INTEGRITY_FAILED: (
        "The local golden knowledge store failed its evidence integrity "
        "check and was not used. Requirements were not evaluated — this is "
        "not a capability gap."
    ),
}


@dataclass(frozen=True, slots=True)
class ClaimsSnapshot:
    """One read-only view of the golden claims plus source display names."""

    state: KnowledgeStoreState
    claims: tuple[CapabilityClaim, ...] = ()
    source_filenames: dict[str, str] = field(default_factory=dict)

    @property
    def note(self) -> str:
        """The static operator-safe sentence for this snapshot state."""
        return STORE_NOTES[self.state]


def load_claims_snapshot(store_root: Path) -> ClaimsSnapshot:
    """Load the golden claims fail-closed; never raise store internals.

    A read must not create store directories, so an absent root is
    reported as ``UNAVAILABLE`` without instantiating the store.
    """
    if not store_root.is_dir():
        return ClaimsSnapshot(state=KnowledgeStoreState.UNAVAILABLE)
    try:
        store = GoldenKnowledgeStore(store_root)
        claims = store.read_claims()
        inventory = store.read_inventory()
    except GoldenStoreIntegrityError:
        return ClaimsSnapshot(state=KnowledgeStoreState.INTEGRITY_FAILED)
    except Exception:  # noqa: BLE001 - a broken store must never raise upward
        return ClaimsSnapshot(state=KnowledgeStoreState.UNREADABLE)
    if not claims:
        return ClaimsSnapshot(state=KnowledgeStoreState.NO_CLAIMS)
    filenames = (
        {source.source_id: source.filename for source in inventory.sources}
        if inventory is not None
        else {}
    )
    return ClaimsSnapshot(
        state=KnowledgeStoreState.AVAILABLE,
        claims=claims,
        source_filenames=filenames,
    )
