"""Domain contracts of the Golden Dataset (Domain K).

These models describe curated internal knowledge — never bid or RFP
data. Per ADR-0009 the Golden Dataset is logically and physically
separated from the bid path: nothing in this module references bids,
runs, uploads, or pipeline artifacts, and nothing in the bid path may
write these models.

Three trust levels are kept explicit and must never blur:

- a **real internal source** is inventoried (:class:`KnowledgeSource`);
- a **machine-extracted statement** starts as
  ``ClaimStatus.EXTRACTED_UNVERIFIED`` and can only leave that state
  through an explicit human action (:func:`confirm_claim`,
  :func:`reject_claim`);
- **human-confirmed knowledge** is the only state a match may present
  as verified.

Identifiers here are golden-scoped (``GKS-``/``GKD-``/``GCL-``/``GPV-``)
and deliberately share no format with bid-path IDs, so a value can never
be mistaken for — or smuggled into — an RFP artifact.

Local filesystem paths are **not part of any contract**. Where content
comes from is runtime-only knowledge held by the inventory service; a
serialized artifact carries filenames and hashes, never paths.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from bidfusion.schemas.common import BidfusionModel, SemanticVersion, Sha256Digest

GOLDEN_SCHEMA_VERSION = "1.0.0"

#: Golden-scoped identifiers. The 12-hex-digit tail is derived from
#: content hashes so IDs are deterministic across runs.
SourceId = Annotated[str, Field(pattern=r"^GKS-[0-9a-f]{12}$")]
ProvenanceId = Annotated[str, Field(pattern=r"^GPV-[0-9a-f]{12}$")]
KnowledgeDocumentId = Annotated[str, Field(pattern=r"^GKD-[0-9a-f]{12}$")]
ClaimId = Annotated[str, Field(pattern=r"^GCL-[0-9a-f]{12}$")]
SectionId = Annotated[str, Field(pattern=r"^SEC-\d{4,}$")]


class ServiceFamily(StrEnum):
    """Service family a knowledge source belongs to, from its filename."""

    MANAGED_THREAT_DETECTION = "managed_threat_detection"
    MANAGED_THREAT_RESPONSE = "managed_threat_response"
    EBONDING_ITSM = "ebonding_itsm"
    UNKNOWN = "unknown"


class Technology(StrEnum):
    """Technology platform a knowledge source covers, from its filename."""

    MICROSOFT_DEFENDER_XDR = "microsoft_defender_xdr"
    MICROSOFT_SENTINEL = "microsoft_sentinel"
    MICROSOFT_GENERIC = "microsoft_generic"
    PALO_ALTO_CORTEX_XDR = "palo_alto_cortex_xdr"
    PALO_ALTO_XSIAM = "palo_alto_xsiam"
    SPLUNK = "splunk"
    VECTRA = "vectra"
    GENERIC_MTD = "generic_mtd"
    MANAGED_THREAT_RESPONSE = "managed_threat_response"
    ITSM_EBONDING = "itsm_ebonding"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    """Document family, classified deterministically from filename prefixes."""

    SERVICE_DESCRIPTION = "service_description"
    QA_TECHNOLOGY_GUIDANCE = "qa_technology_guidance"
    SERVICE_ACTIVATION_PROCEDURE = "service_activation_procedure"
    SERVICE_INSTRUCTION = "service_instruction"
    CHECKLIST = "checklist"
    CUSTOMER_PRESENTATION = "customer_presentation"
    DATASHEET = "datasheet"
    OVERVIEW = "overview"
    PRICING_COMMERCIAL = "pricing_commercial"
    OFFERING_ESTIMATE = "offering_estimate"
    OPERATIONAL_HANDBOOK = "operational_handbook"
    SERVICE_CATALOGUE = "service_catalogue"
    STATEMENT_OF_WORK = "statement_of_work"
    UNKNOWN = "unknown"


class ParseSupport(StrEnum):
    """Whether a reviewed parser exists for the source format."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ParseStatus(StrEnum):
    """Outcome of safe parsing for one source."""

    NOT_PARSED = "NOT_PARSED"
    PARSED = "PARSED"
    PARSE_FAILED = "PARSE_FAILED"
    PARSE_UNSUPPORTED = "PARSE_UNSUPPORTED"


class IngestionStatus(StrEnum):
    """How far one source travelled through the golden pipeline."""

    INVENTORIED = "INVENTORIED"
    INGESTED = "INGESTED"
    INGESTION_FAILED = "INGESTION_FAILED"
    NOT_SELECTED = "NOT_SELECTED"


class HumanReviewStatus(StrEnum):
    """Whether a human has looked at a machine-produced record."""

    REQUIRED = "REQUIRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ClaimStatus(StrEnum):
    """Trust state of a capability claim; extraction never confirms."""

    EXTRACTED_UNVERIFIED = "EXTRACTED_UNVERIFIED"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ExtractionStatus(StrEnum):
    """Completeness of the deterministic content extraction."""

    EXTRACTED = "EXTRACTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProvenanceStatus(StrEnum):
    """Whether every section carries a full source locator."""

    PROVENANCE_FULL = "PROVENANCE_FULL"
    PROVENANCE_PARTIAL = "PROVENANCE_PARTIAL"


class ConfidenceBand(StrEnum):
    """Coarse, deterministic confidence for a rule-extracted claim."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CapabilityCategory(StrEnum):
    """Pilot capability taxonomy for rule-based claim extraction."""

    TWENTY_FOUR_SEVEN_MONITORING = "24_7_monitoring"
    MICROSOFT_SENTINEL_SUPPORT = "microsoft_sentinel_support"
    MICROSOFT_DEFENDER_XDR_SUPPORT = "microsoft_defender_xdr_support"
    PALO_ALTO_CORTEX_SUPPORT = "palo_alto_cortex_support"
    SPLUNK_SUPPORT = "splunk_support"
    VECTRA_SUPPORT = "vectra_support"
    INCIDENT_ISOLATION = "incident_isolation"
    TRANSITION_ACTIVATION = "transition_activation"
    HANDOVER_TO_OPERATIONS = "handover_to_operations"
    SERVICE_INTEGRATION = "service_integration"


class MatchStatus(StrEnum):
    """Deterministic pilot verdict for one requirement against the claims."""

    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    GAP = "GAP"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"


class KnowledgeSourceLocator(BidfusionModel):
    """Typed location inside one golden source; at least one field is set.

    The locator vocabulary mirrors what the reviewed parsers can actually
    provide per format — DOCX paragraph/table positions, PDF pages, XLSX
    sheet/cell ranges, TXT line ranges — and nothing more. Locators are
    never invented: a section whose parser gave no position gets
    ``whole_document`` plus ``ProvenanceStatus.PROVENANCE_PARTIAL`` on the
    document.
    """

    whole_document: bool = False
    page: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=0)
    heading: str | None = Field(default=None, min_length=1)
    table: str | None = Field(default=None, min_length=1)
    sheet: str | None = Field(default=None, min_length=1)
    cell_range: str | None = Field(default=None, min_length=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _locates_something(self) -> KnowledgeSourceLocator:
        located = self.whole_document or any(
            value is not None
            for value in (
                self.page,
                self.paragraph_index,
                self.heading,
                self.table,
                self.sheet,
                self.cell_range,
                self.line_start,
                self.line_end,
            )
        )
        if not located:
            msg = "a knowledge source locator must identify a location"
            raise ValueError(msg)
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            msg = "line range end must not precede its start"
            raise ValueError(msg)
        return self


class KnowledgeSource(BidfusionModel):
    """Inventory record for one real internal source file.

    Deliberately path-free: the mapping from ``source_id`` to a local
    file lives only in the runtime inventory service, so no serialized
    artifact or UI view can ever leak a local directory layout.
    """

    source_id: SourceId
    filename: str = Field(min_length=1)
    extension: str = Field(min_length=1)
    file_size: int = Field(ge=0)
    source_hash: Sha256Digest
    service_family: ServiceFamily
    technology: Technology
    document_type: DocumentType
    version: str | None = Field(default=None, min_length=1)
    parse_support: ParseSupport
    parse_status: ParseStatus
    ingestion_status: IngestionStatus
    review_status: HumanReviewStatus
    provenance_id: ProvenanceId


class KnowledgeInventory(BidfusionModel):
    """One complete, ordered inventory snapshot of a golden source set."""

    schema_version: SemanticVersion = GOLDEN_SCHEMA_VERSION
    dataset_label: str = Field(min_length=1)
    sources: tuple[KnowledgeSource, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _source_ids_are_unique(self) -> KnowledgeInventory:
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            msg = "inventory source IDs must be unique"
            raise ValueError(msg)
        return self


class KnowledgeProvenance(BidfusionModel):
    """Document-level provenance binding extracted content to exact bytes."""

    source_id: SourceId
    filename: str = Field(min_length=1)
    source_hash: Sha256Digest
    document_version: str | None = Field(default=None, min_length=1)
    locator: KnowledgeSourceLocator


class KnowledgeSection(BidfusionModel):
    """One normalized content section with its own source locator."""

    section_id: SectionId
    heading: str | None = Field(default=None, min_length=1)
    text: str = Field(min_length=1)
    source_locator: KnowledgeSourceLocator
    source_id: SourceId


class KnowledgeDocument(BidfusionModel):
    """Normalized knowledge extracted from exactly one source."""

    knowledge_document_id: KnowledgeDocumentId
    source_id: SourceId
    schema_version: SemanticVersion
    title: str = Field(min_length=1)
    service_family: ServiceFamily
    technology: Technology
    document_type: DocumentType
    source_version: str | None = Field(default=None, min_length=1)
    sections: tuple[KnowledgeSection, ...] = Field(default_factory=tuple)
    provenance: KnowledgeProvenance
    extraction_status: ExtractionStatus
    review_status: HumanReviewStatus
    provenance_status: ProvenanceStatus

    @model_validator(mode="after")
    def _document_is_coherent(self) -> KnowledgeDocument:
        if self.provenance.source_id != self.source_id:
            msg = "document provenance must reference the document source"
            raise ValueError(msg)
        for section in self.sections:
            if section.source_id != self.source_id:
                msg = "every section must reference the document source"
                raise ValueError(msg)
        section_ids = [section.section_id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            msg = "section IDs must be unique within a document"
            raise ValueError(msg)
        return self


class EvidenceReference(BidfusionModel):
    """Pointer from a claim or match into exact source content."""

    source_id: SourceId
    section_id: SectionId
    locator: KnowledgeSourceLocator
    source_version: str | None = Field(default=None, min_length=1)


class CapabilityClaim(BidfusionModel):
    """One machine-extracted capability statement, never born verified.

    Construction enforces the two trust rules of this domain: no claim
    without evidence, and no claim enters existence as human-confirmed.
    ``HUMAN_CONFIRMED`` is reachable only through :func:`confirm_claim`.
    """

    claim_id: ClaimId
    service_family: ServiceFamily
    technology: Technology
    capability: CapabilityCategory
    statement: str = Field(min_length=1)
    status: ClaimStatus = ClaimStatus.EXTRACTED_UNVERIFIED
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)
    confidence_band: ConfidenceBand
    human_review_status: HumanReviewStatus = HumanReviewStatus.REQUIRED
    reviewed_by: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _trust_states_are_coherent(self) -> CapabilityClaim:
        if self.status is ClaimStatus.HUMAN_CONFIRMED:
            if self.human_review_status is not HumanReviewStatus.CONFIRMED:
                msg = "a human-confirmed claim requires a confirmed review status"
                raise ValueError(msg)
            if self.reviewed_by is None:
                msg = "a human-confirmed claim must name its reviewer"
                raise ValueError(msg)
        if self.status is ClaimStatus.EXTRACTED_UNVERIFIED and (
            self.human_review_status is HumanReviewStatus.CONFIRMED
        ):
            msg = "an unverified claim cannot carry a confirmed review status"
            raise ValueError(msg)
        return self


def confirm_claim(claim: CapabilityClaim, *, reviewer: str) -> CapabilityClaim:
    """Explicit human confirmation — the only path to ``HUMAN_CONFIRMED``."""
    if not reviewer.strip():
        msg = "claim confirmation requires a named reviewer"
        raise ValueError(msg)
    return claim.model_copy(
        update={
            "status": ClaimStatus.HUMAN_CONFIRMED,
            "human_review_status": HumanReviewStatus.CONFIRMED,
            "reviewed_by": reviewer,
        }
    )


def reject_claim(claim: CapabilityClaim, *, reviewer: str) -> CapabilityClaim:
    """Explicit human rejection of an extracted claim."""
    if not reviewer.strip():
        msg = "claim rejection requires a named reviewer"
        raise ValueError(msg)
    return claim.model_copy(
        update={
            "status": ClaimStatus.REJECTED,
            "human_review_status": HumanReviewStatus.REJECTED,
            "reviewed_by": reviewer,
        }
    )


class RequirementCandidate(BidfusionModel):
    """One requirement fed into pilot matching; synthetic in this slice."""

    requirement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    technology_hint: Technology | None = None
    capability_hint: CapabilityCategory | None = None


class MatchCandidate(BidfusionModel):
    """Deterministic pilot verdict for one requirement."""

    requirement_id: str = Field(min_length=1)
    claim_id: ClaimId | None = None
    match_status: MatchStatus
    rationale: str = Field(min_length=1)
    evidence_refs: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    human_review_status: HumanReviewStatus = HumanReviewStatus.REQUIRED

    @model_validator(mode="after")
    def _matched_needs_a_claim(self) -> MatchCandidate:
        if self.match_status in (MatchStatus.MATCHED, MatchStatus.PARTIAL) and (
            self.claim_id is None
        ):
            msg = "a matched or partial verdict must reference a claim"
            raise ValueError(msg)
        return self
