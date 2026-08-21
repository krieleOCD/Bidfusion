"""View models for the Golden Knowledge pilot pages.

This module reads the local golden runtime store and turns it into
path-free view models. Trust levels stay visible end to end: sources are
REAL INTERNAL KNOWLEDGE, claims are machine-extracted and unverified,
and the matching requirements are SYNTHETIC DEMO INPUT. Nothing here
mutates the store, calls a model, or touches the network.

A missing or unreadable store is a normal state, not an error: the pages
render an honest empty state instead of a traceback, and no exception
text from parsing real content ever reaches a template.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeInventory,
    KnowledgeSource,
    ParseStatus,
    ParseSupport,
)
from bidfusion.golden_dataset.matching import (
    SYNTHETIC_DEMO_REQUIREMENTS,
    match_requirements,
)
from bidfusion.golden_dataset.store import GoldenKnowledgeStore

#: Honest banner lines every golden page shows verbatim.
PILOT_LABELS = (
    "INTERNAL KNOWLEDGE PILOT",
    "LOCAL DATASET",
    "NOT COMMITTED TO REPOSITORY",
    "HUMAN REVIEW REQUIRED",
)

_EMPTY_STORE_NOTE = (
    "There is no local golden knowledge store on this machine yet. Run the "
    "golden ingestion script against a local source directory to build one."
)
_BROKEN_STORE_NOTE = (
    "The local golden knowledge store could not be read. Its files may be "
    "incomplete or damaged; re-run the golden ingestion script to rebuild it."
)

_CAPABILITY_LABELS: dict[CapabilityCategory, str] = {
    CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING: "24/7 monitoring",
    CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT: "Microsoft Sentinel support",
    CapabilityCategory.MICROSOFT_DEFENDER_XDR_SUPPORT: "Microsoft Defender XDR support",
    CapabilityCategory.PALO_ALTO_CORTEX_SUPPORT: "Palo Alto Cortex XDR/XSIAM support",
    CapabilityCategory.SPLUNK_SUPPORT: "Splunk support",
    CapabilityCategory.VECTRA_SUPPORT: "Vectra support",
    CapabilityCategory.INCIDENT_ISOLATION: "Incident isolation",
    CapabilityCategory.TRANSITION_ACTIVATION: "Transition and activation",
    CapabilityCategory.HANDOVER_TO_OPERATIONS: "Handover to operations",
    CapabilityCategory.SERVICE_INTEGRATION: "Service integration (ITSM/eBonding)",
}


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One inventory table row; filename only, never a path."""

    filename: str
    document_type: str
    technology: str
    version: str
    parse_support: str
    ingestion_status: str


@dataclass(frozen=True, slots=True)
class InventoryView:
    """Everything the inventory page renders."""

    available: bool
    note: str | None
    dataset_label: str
    total: int
    parsed: int
    unsupported: int
    parse_failed: int
    ingested: int
    not_selected: int
    review_required: int
    technologies: tuple[tuple[str, int], ...]
    document_families: tuple[tuple[str, int], ...]
    rows: tuple[SourceRow, ...]
    warnings: tuple[str, ...]
    labels: tuple[str, ...] = PILOT_LABELS


@dataclass(frozen=True, slots=True)
class EvidenceView:
    """One evidence pointer, resolved to its source filename."""

    filename: str
    section_id: str
    source_version: str


@dataclass(frozen=True, slots=True)
class MatchRow:
    """One requirement matched against the claims."""

    requirement_id: str
    requirement_text: str
    match_status: str
    capability: str
    claim_statement: str
    confidence_band: str
    rationale: str
    evidence: tuple[EvidenceView, ...]
    human_review: str


#: Label texts the matching page renders verbatim. They live here, not
#: in the template, so the template hardcodes no status vocabulary.
SYNTHETIC_REQUIREMENT_LABEL = "CUSTOMER REQUIREMENT (SYNTHETIC DEMO INPUT)"

_MATCHING_METHOD_NOTE = (
    "The requirements below are SYNTHETIC DEMO INPUT — written for this pilot, "
    "not taken from any customer RFP. They are matched by fixed capability "
    "keywords against {count} machine-extracted capability claims from real "
    "internal MTD documentation. Every claim is EXTRACTED UNVERIFIED and every "
    "match stays HUMAN REVIEW REQUIRED: a match here confirms nothing until a "
    "person does. No embeddings, no vector database, no LLM."
)


@dataclass(frozen=True, slots=True)
class MatchingView:
    """Everything the matching page renders."""

    available: bool
    note: str | None
    claim_count: int
    rows: tuple[MatchRow, ...]
    labels: tuple[str, ...] = PILOT_LABELS
    requirement_label: str = SYNTHETIC_REQUIREMENT_LABEL

    @property
    def method_note(self) -> str:
        """The verbatim explanation of how these matches are produced."""
        return _MATCHING_METHOD_NOTE.format(count=self.claim_count)


def load_inventory_view(store_root: Path) -> InventoryView:
    """Build the inventory page model; absent or broken stores stay calm."""
    inventory, readable = _read_inventory(store_root)
    if inventory is None:
        return _empty_inventory_view(_EMPTY_STORE_NOTE if readable else _BROKEN_STORE_NOTE)

    sources = inventory.sources
    status_counts = Counter(source.parse_status for source in sources)
    return InventoryView(
        available=True,
        note=None,
        dataset_label=inventory.dataset_label,
        total=len(sources),
        parsed=status_counts[ParseStatus.PARSED],
        unsupported=status_counts[ParseStatus.PARSE_UNSUPPORTED],
        parse_failed=status_counts[ParseStatus.PARSE_FAILED],
        ingested=sum(
            1 for source in sources if source.ingestion_status is IngestionStatus.INGESTED
        ),
        not_selected=sum(
            1 for source in sources if source.ingestion_status is IngestionStatus.NOT_SELECTED
        ),
        review_required=sum(
            1 for source in sources if source.review_status is HumanReviewStatus.REQUIRED
        ),
        technologies=_distribution(source.technology.value for source in sources),
        document_families=_distribution(source.document_type.value for source in sources),
        rows=tuple(_source_row(source) for source in sources),
        warnings=inventory.warnings,
    )


def load_matching_view(store_root: Path) -> MatchingView:
    """Build the matching page model from stored claims, deterministically."""
    inventory, readable = _read_inventory(store_root)
    claims = _read_claims(store_root)
    if not readable or claims is None:
        return MatchingView(available=False, note=_BROKEN_STORE_NOTE, claim_count=0, rows=())
    if inventory is None or not claims:
        return MatchingView(available=False, note=_EMPTY_STORE_NOTE, claim_count=0, rows=())

    filenames = {source.source_id: source.filename for source in inventory.sources}
    claims_by_id = {claim.claim_id: claim for claim in claims}
    matches = match_requirements(SYNTHETIC_DEMO_REQUIREMENTS, claims)
    requirements = {item.requirement_id: item for item in SYNTHETIC_DEMO_REQUIREMENTS}

    rows = []
    for match in matches:
        claim = claims_by_id.get(match.claim_id) if match.claim_id is not None else None
        requirement = requirements[match.requirement_id]
        rows.append(
            MatchRow(
                requirement_id=match.requirement_id,
                requirement_text=requirement.text,
                match_status=match.match_status.value.replace("_", " "),
                capability=(_CAPABILITY_LABELS[claim.capability] if claim is not None else "—"),
                claim_statement=claim.statement if claim is not None else "—",
                confidence_band=claim.confidence_band.value if claim is not None else "—",
                rationale=match.rationale,
                evidence=tuple(
                    EvidenceView(
                        filename=filenames.get(reference.source_id, "unknown source"),
                        section_id=reference.section_id,
                        source_version=reference.source_version or "—",
                    )
                    for reference in match.evidence_refs
                ),
                human_review="HUMAN REVIEW REQUIRED",
            )
        )
    return MatchingView(available=True, note=None, claim_count=len(claims), rows=tuple(rows))


def _read_inventory(store_root: Path) -> tuple[KnowledgeInventory | None, bool]:
    """The stored inventory plus a readability flag (False = damaged).

    A GET must not create directories: an absent root is simply an empty
    store, and only an existing-but-unreadable one counts as damaged.
    """
    if not store_root.is_dir():
        return None, True
    try:
        return GoldenKnowledgeStore(store_root).read_inventory(), True
    except Exception:  # noqa: BLE001 - a broken store must never raise into a page
        return None, False


def _read_claims(store_root: Path) -> tuple[CapabilityClaim, ...] | None:
    if not store_root.is_dir():
        return ()
    try:
        return GoldenKnowledgeStore(store_root).read_claims()
    except Exception:  # noqa: BLE001 - a broken store must never raise into a page
        return None


def _empty_inventory_view(note: str) -> InventoryView:
    return InventoryView(
        available=False,
        note=note,
        dataset_label="",
        total=0,
        parsed=0,
        unsupported=0,
        parse_failed=0,
        ingested=0,
        not_selected=0,
        review_required=0,
        technologies=(),
        document_families=(),
        rows=(),
        warnings=(),
    )


def _source_row(source: KnowledgeSource) -> SourceRow:
    return SourceRow(
        filename=source.filename,
        document_type=source.document_type.value.replace("_", " "),
        technology=source.technology.value.replace("_", " "),
        version=source.version or "—",
        parse_support=(
            "PARSE UNSUPPORTED"
            if source.parse_support is ParseSupport.UNSUPPORTED
            else source.parse_status.value.replace("_", " ")
        ),
        ingestion_status=source.ingestion_status.value.replace("_", " "),
    )


def _distribution(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(value.replace("_", " ") for value in values)
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
