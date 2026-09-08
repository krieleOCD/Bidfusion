"""The single source of truth for what BidFusion can do today, and when.

Every product surface in the local UI declares itself here: its status,
which kind of data it renders, which phase it belongs to, what it can
and cannot do, and what has to happen before it can claim more. Nothing
in a template, route, or view model may state a status of its own — they
project what this module records.

The registry is static configuration. It performs no I/O, holds no
paths, credentials, or environment values, and imports nothing from the
pipeline, the security services, or the LLM gateway.

Phase identifiers follow the repository's own binding architecture
contract (docs/architecture/level-1-target.md): the product stages
Level 0.4 / Level 1A / Level 1B from its section 4, and the six Level 1
slices from its section 13. Phases beyond Level 1 are not yet fixed in
any architecture document and are marked ``PROPOSED`` accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeatureStatus(StrEnum):
    """How far one product surface has actually been built."""

    LIVE = "LIVE"
    """Implemented and serving its real source in this build."""

    DEMO = "DEMO"
    """Implemented as a demonstration over curated, non-real data."""

    PLANNED = "PLANNED"
    """Not built. The surface shows the intended information model only."""

    BLOCKED = "BLOCKED"
    """Cannot proceed until an external decision or approval lands."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    """Built, but not connected pending a governance or security review."""


class DataMode(StrEnum):
    """Where the data a surface renders actually comes from."""

    VERIFIED_ARTIFACTS = "VERIFIED_ARTIFACTS"
    """Versioned pipeline artifacts, re-verified against their manifest."""

    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    """The repository's own generated fixture packages, run for real."""

    CURATED_DEMO = "CURATED_DEMO"
    """Hand-authored, versioned demonstration data. Invented, never real."""

    STATIC_PREVIEW = "STATIC_PREVIEW"
    """Static configuration or layout only. No data source behind it."""

    NOT_CONNECTED = "NOT_CONNECTED"
    """No source of any kind is wired up."""

    LOCAL_INTERNAL_PILOT = "LOCAL_INTERNAL_PILOT"
    """A local, gitignored runtime store derived from real internal documents
    on this machine. Never committed, never claimed validated; every record
    stays marked for human review."""


class Visibility(StrEnum):
    """Where a feature appears in the product shell."""

    PRIMARY_NAV = "PRIMARY_NAV"
    """One of the top-level worlds in the product navigation."""

    MODULE_PAGE = "MODULE_PAGE"
    """A page of its own, reached through a sub-navigation."""

    MODULE_SECTION = "MODULE_SECTION"
    """A section inside another feature's page, plus its own detail page."""


class PhaseState(StrEnum):
    """How far a delivery phase has progressed."""

    DELIVERED = "DELIVERED"
    NEXT = "NEXT"
    PLANNED = "PLANNED"
    BLOCKED = "BLOCKED"


class PhaseDefinition(StrEnum):
    """Whether a phase is fixed in an architecture document, or proposed."""

    ARCHITECTURE_CONTRACT = "ARCHITECTURE_CONTRACT"
    """Named in a binding architecture document in this repository."""

    PROPOSED = "PROPOSED"
    """Proposed by this product plan. No architecture document defines it."""


@dataclass(frozen=True, slots=True)
class Phase:
    """One delivery phase of the BidFusion product."""

    phase_id: str
    title: str
    summary: str
    state: PhaseState
    definition: PhaseDefinition
    definition_reference: str


@dataclass(frozen=True, slots=True)
class Feature:
    """One product surface and everything the shell may claim about it."""

    key: str
    title: str
    short_description: str
    status: FeatureStatus
    data_mode: DataMode
    target_phase: str
    owner: str
    dependencies: tuple[str, ...]
    current_capabilities: tuple[str, ...]
    planned_capabilities: tuple[str, ...]
    current_sources: tuple[str, ...]
    future_sources: tuple[str, ...]
    limitations: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    route_name: str
    visibility: Visibility


#: Delivery phases, in order. Level 0.4 / 1A / 1B and the six Level 1
#: slices come from docs/architecture/level-1-target.md; everything above
#: Level 1 is proposed by this product plan and says so.
PHASES: tuple[Phase, ...] = (
    Phase(
        phase_id="L0.4",
        title="Local synthetic walking skeleton",
        summary=(
            "The local UI drives the repository's own synthetic fixture packages "
            "through the real pipeline: intake, deterministic preflight, package "
            "gate, parsing, rule-based extraction, normalization, quality gate, "
            "and working- or review-package generation."
        ),
        state=PhaseState.DELIVERED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 4",
    ),
    Phase(
        phase_id="L1A-S1",
        title="Upload and quarantine",
        summary=(
            "An explicitly authorized internal user uploads a non-production test "
            "package. Acceptance policy, quarantine, upload manifest, and the "
            "BidRun lifecycle up to QUARANTINED. Quarantine is containment, not "
            "a security clearance."
        ),
        state=PhaseState.DELIVERED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.1",
    ),
    Phase(
        phase_id="L1A-S2",
        title="Security review of quarantined packages",
        summary=(
            "Wire the existing deterministic preflight scanner and package-gate "
            "policy onto quarantined uploads and formalize the security scanner "
            "port. Moves a BidRun from QUARANTINED to SECURITY_REVIEW."
        ),
        state=PhaseState.NEXT,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.2",
    ),
    Phase(
        phase_id="L1A-S3",
        title="Cleared to processing",
        summary=(
            "The first point at which quarantine hands cleared bytes to the "
            "existing processing pipeline. Moves a BidRun from SECURITY_REVIEW "
            "through CLEARED to PROCESSING."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.3",
    ),
    Phase(
        phase_id="L1A-S4",
        title="Human review",
        summary=(
            "A review repository port and a reviewer surface over extracted "
            "requirements, deadlines, and formalities with their sources, plus "
            "explicit REVIEW_REQUIRED handling."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.4",
    ),
    Phase(
        phase_id="L1A-S5",
        title="Reviewed working package",
        summary=(
            "A versioned output that combines machine extraction with recorded "
            "human review decisions. The point at which COMPLETED and FAILED "
            "become reachable for an uploaded package."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.5",
    ),
    Phase(
        phase_id="L1A-S6",
        title="Evaluation harness",
        summary=(
            "An evaluation port wired to the golden dataset, so extraction "
            "quality is measured against known-good expectations rather than "
            "asserted."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, section 13.6",
    ),
    Phase(
        phase_id="L1B",
        title="Production customer data",
        summary=(
            "Real customer RFPs. Requires a production security gate, "
            "operational controls, identity, and a retention and deletion "
            "policy. Explicitly out of scope until a separate decision is taken."
        ),
        state=PhaseState.BLOCKED,
        definition=PhaseDefinition.ARCHITECTURE_CONTRACT,
        definition_reference="docs/architecture/level-1-target.md, sections 4 and 14",
    ),
    Phase(
        phase_id="L2-A",
        title="Governed model egress",
        summary=(
            "Connect the existing Orange LLM proxy gateway to the processing "
            "pipeline under an explicit data-classification policy, so model "
            "assistance becomes available without an uncontrolled egress path."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="L2-B",
        title="Customer intelligence",
        summary=(
            "Consolidate validated opportunity context from approved internal "
            "systems. Requires a connector decision and a governance approval "
            "per source before any of it is built."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="L2-C",
        title="Competitive intelligence",
        summary=(
            "Competitor monitoring from approved, attributable sources with "
            "recorded collection dates, so a claim about a competitor can "
            "always be traced back to where it came from and when."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="L2-D",
        title="Capability and compliance matching",
        summary=(
            "Match extracted requirements against a governed capability and "
            "evidence catalog, with an explicit unknown state and a named human "
            "owner for every unconfirmed match."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="L2-E",
        title="Qualification and win strategy",
        summary=(
            "Structured qualification and win-theme development on top of "
            "compliance and capability results. The system assesses; the bid "
            "board decides."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="L2-F",
        title="Proposal factory",
        summary=(
            "Grounded drafting support over reviewed requirements and approved "
            "content, with mandatory human review before anything reaches a "
            "customer."
        ),
        state=PhaseState.PLANNED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference="Proposed by this product plan. No architecture document defines it.",
    ),
    Phase(
        phase_id="GK-P1",
        title="Golden knowledge pilot (MTD)",
        summary=(
            "First real internal knowledge area: a local, read-only inventory "
            "and deterministic ingestion of the Managed Threat Detection "
            "document set into a gitignored runtime store, with rule-extracted, "
            "unverified capability claims and a deterministic demo matching. "
            "Separated from the bid path per ADR-0009."
        ),
        state=PhaseState.DELIVERED,
        definition=PhaseDefinition.PROPOSED,
        definition_reference=(
            "Proposed by this product plan; no architecture document defines it. "
            "Described in docs/development/golden-dataset-mtd-pilot.md."
        ),
    ),
)


_PLATFORM = "BidFusion Platform Team"
_SECURITY = "BidFusion Security Engineering"
_BID_MANAGEMENT = "BidFusion Bid Management"
_SECURITY_AND_LEGAL = "BidFusion Security and Legal"

_HUMAN_REVIEW_LIMIT = "Every result requires human review before it is used in a bid."
_NO_LIVE_CONNECTOR = "No live connector exists. Nothing is fetched from any system."
_NO_MODEL_CALL = "No model call is made anywhere in this surface."


FEATURES: tuple[Feature, ...] = (
    Feature(
        key="product_overview",
        title="Product Overview",
        short_description=(
            "The map of the product: which modules exist, what each one really "
            "does today, and which phase the rest belongs to."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.STATIC_PREVIEW,
        target_phase="L0.4",
        owner=_PLATFORM,
        dependencies=(),
        current_capabilities=(
            "Lists every product module with its status, data mode, and phase",
            "Links to each module and to its full feature record",
            "Separates implemented, demonstrated, planned, and blocked work",
        ),
        planned_capabilities=("Show delivery progress per phase once phases start closing",),
        current_sources=("The BidFusion feature registry (static configuration)",),
        future_sources=(),
        limitations=("Describes intent and status. It is not a build or release report.",),
        acceptance_criteria=(
            "Every registered feature appears exactly once",
            "No module card claims a status the registry does not record",
        ),
        route_name="overview",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="rfp_intake",
        title="RFP Intake and Quarantine",
        short_description=(
            "Authorized non-production test packages are inventoried, integrity "
            "stamped, and held in quarantine. Quarantine is containment, not "
            "clearance."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.VERIFIED_ARTIFACTS,
        target_phase="L1A-S1",
        owner=_SECURITY,
        dependencies=(),
        current_capabilities=(
            "Accepts PDF, XLSX, and TXT after an explicit authorization confirmation",
            "Enforces per-file, per-package, and file-count limits server-side",
            "Rejects extension mismatches and macro-bearing office files",
            "Writes an upload manifest with a hash per file and re-verifies it on read",
        ),
        planned_capabilities=(
            "Hand a quarantined package to the security review lane",
            "Show the BidRun state history on the package page",
        ),
        current_sources=("Uploaded files held in the local quarantine store",),
        future_sources=(),
        limitations=(
            "Uploaded files are never parsed, extracted, or security cleared",
            "A quarantined package cannot advance past QUARANTINED in this build",
            "Authorized non-production test data only. Never production customer data.",
        ),
        acceptance_criteria=(
            "An upload without the authorization confirmation is refused outright",
            "The only status a free upload can reach is QUARANTINED",
            "A tampered package directory refuses to render instead of degrading",
        ),
        route_name="index",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="synthetic_analysis",
        title="Synthetic RFP Analysis",
        short_description=(
            "The repository's own fixture packages run through the real "
            "pipeline end to end, so the analysis path can be exercised without "
            "any customer document."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.SYNTHETIC_FIXTURE,
        target_phase="L0.4",
        owner=_PLATFORM,
        dependencies=(),
        current_capabilities=(
            "Runs deterministic preflight and the package gate on a fixture package",
            "Runs parsing, rule-based extraction, normalization, and the quality gate",
            "Records every stage outcome as a versioned artifact",
        ),
        planned_capabilities=("Run the same path on a security-cleared uploaded package",),
        current_sources=("The repository's synthetic fixture packages",),
        future_sources=("Security-cleared uploaded packages",),
        limitations=(
            "Only the repository's own fixture packages can be processed",
            "Extraction is rule-based. No model is involved.",
        ),
        acceptance_criteria=(
            "Only fixture packages the service itself enumerates can be started",
            "Every displayed stage outcome comes from the recorded run summary",
        ),
        route_name="index",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="package_security_gate",
        title="Package Security Gate",
        short_description=(
            "The recorded gate decision for one run: per-document verdicts, the "
            "reasons behind them, and what the pipeline did as a result."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.VERIFIED_ARTIFACTS,
        target_phase="L0.4",
        owner=_SECURITY,
        dependencies=(),
        current_capabilities=(
            "Shows the gate decision, its policy identifier, and its reasons",
            "Shows the security verdict recorded for every document",
            "Blocks a whole package when any document fails",
        ),
        planned_capabilities=("Apply the same gate to quarantined uploads",),
        current_sources=("The package-gate artifact of the run",),
        future_sources=(),
        limitations=(
            "Deterministic development-time checks. A pass is not a production clearance.",
            "No malware signatures, no sandboxed parsing, no resource limits",
        ),
        acceptance_criteria=(
            "The gate decision is read from the artifact and never recomputed for display",
            "A blocked package offers no path to processing",
        ),
        route_name="show_run",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="working_package",
        title="Working Package",
        short_description=(
            "The evidence-bearing result of a completed run: requirements, "
            "deadlines, formalities, and open questions, each with the source "
            "it came from."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.VERIFIED_ARTIFACTS,
        target_phase="L0.4",
        owner=_PLATFORM,
        dependencies=(),
        current_capabilities=(
            "Shows normalized requirements split by modality and category",
            "Shows the extracted timeline and submission formalities",
            "Names the document, page, or cell behind every statement",
            "Offers the versioned package as JSON and Markdown",
            "Generates a versioned, integrity-checked reviewed working package "
            "that carries recorded human review decisions",
        ),
        planned_capabilities=(),
        current_sources=("The working-package artifacts of the run",),
        future_sources=(),
        limitations=(
            "Only a completed run with an acceptable quality gate renders this view",
            "Rule-based extraction. Coverage is bounded by what the rules recognize.",
        ),
        acceptance_criteria=(
            "Artifacts are refused when the run's integrity manifest does not verify",
            "Every statement carries at least one source reference",
        ),
        route_name="show_working_package",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="quality_review_package",
        title="Quality Gate and Review Package",
        short_description=(
            "When extraction quality is not good enough to stand on its own, "
            "the run produces an explicitly marked review package instead of a "
            "working package."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.VERIFIED_ARTIFACTS,
        target_phase="L0.4",
        owner=_PLATFORM,
        dependencies=(),
        current_capabilities=(
            "Records a quality status with the signals that produced it",
            "Produces a review package that names the required manual actions",
            "Keeps partial detections visibly separate from confirmed results",
        ),
        planned_capabilities=(
            "Let a reviewer resolve the flagged items directly in the interface",
        ),
        current_sources=("The quality-gate and review-package artifacts of the run",),
        future_sources=(),
        limitations=(
            "The review package is never presented as a complete working package",
            "The interface cannot release or override a quality decision",
        ),
        acceptance_criteria=(
            "A review-required run offers the review package and no working package",
            "Every review package states that it is not a complete working package",
        ),
        route_name="show_review_package",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="upload_security_review",
        title="Security Review of Uploaded Packages",
        short_description=(
            "The lane that will carry a quarantined upload through the security "
            "gate and, once cleared, into processing."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.NOT_CONNECTED,
        target_phase="L1A-S2",
        owner=_SECURITY,
        dependencies=(
            "Formal security scanner port",
            "Package-gate policy applied to quarantined bytes",
            "BidRun transition from QUARANTINED to SECURITY_REVIEW",
        ),
        current_capabilities=(),
        planned_capabilities=(
            "Run the deterministic preflight over a quarantined package",
            "Record a gate decision against the BidRun",
            "Release a cleared package into the existing processing path",
        ),
        current_sources=(),
        future_sources=("Quarantined upload packages",),
        limitations=(
            "Not built. An uploaded package stops at QUARANTINED in this build.",
            "No automatic clearance will ever be added without an explicit decision",
        ),
        acceptance_criteria=(
            "An uploaded package can only leave quarantine through a recorded gate decision",
            "A blocked upload can never reach a parser",
        ),
        route_name="index",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="customer_intelligence",
        title="Customer Intelligence",
        short_description=(
            "The opportunity context that already exists inside the company: "
            "account history, prior bids, stakeholders, and what colleagues "
            "already know."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-B",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "CRM integration decision",
            "Connector platform evaluation",
            "Document archive permission model",
            "Communication-data governance approval",
        ),
        current_capabilities=(
            "Shows the intended information model over curated demonstration data",
            "Names, per source, what would be retrieved and what governs it",
        ),
        planned_capabilities=(
            "Retrieve opportunity and account metadata from the CRM",
            "Surface prior proposals and agreements from the bid archive",
            "Summarize recorded stakeholder context from approved sources",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "CRM opportunity and account records",
            "Bid archive and prior proposals",
            "Approved internal communication records",
        ),
        limitations=(
            _NO_LIVE_CONNECTOR,
            "No real account, contact, or opportunity data is shown",
            "No stakeholder analysis is performed",
        ),
        acceptance_criteria=(
            "Every source card states its connection status before its content",
            "No page element implies a live retrieval from any system",
        ),
        route_name="customer_intelligence",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="qualification",
        title="Qualification",
        short_description=(
            "Structured bid or no-bid assessment: must-pass factors, evidence "
            "gaps, owners, and the conditions attached to a go."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-E",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Compliance results",
            "Capability fit results",
            "Agreed qualification criteria and scoring",
        ),
        current_capabilities=(
            "Shows the intended qualification model over curated demonstration data",
            "Separates the system assessment from the human decision throughout",
        ),
        planned_capabilities=(
            "Derive must-pass factors from extracted exclusion criteria",
            "Track conditions, owners, and due dates to closure",
            "Record the bid board decision against the assessment it responded to",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "Compliance and capability results of the same bid",
            "Recorded bid board decisions",
        ),
        limitations=(
            "Not built. Nothing on this page is derived from a real assessment.",
            "A system assessment is never a decision. The bid board decides.",
        ),
        acceptance_criteria=(
            "The interface never labels a system assessment as a decision",
            "Every recommendation names the human decision owner",
        ),
        route_name="qualification",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="compliance",
        title="Compliance",
        short_description=(
            "Exclusion criteria and mandatory requirements with an explicit "
            "compliance state, the evidence behind it, and who owns each open "
            "item."
        ),
        status=FeatureStatus.DEMO,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-D",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Governed capability and evidence catalog",
            "Human confirmation workflow",
        ),
        current_capabilities=(
            "Demonstrates the compliance model over curated demonstration data",
            "Distinguishes compliant, partial, unknown, and clarification-required",
        ),
        planned_capabilities=(
            "Build the matrix from the extracted requirements of a real run",
            "Attach approved evidence to each mandatory requirement",
            "Track clarification questions to the customer through to answer",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "Normalized requirements of a processed run",
            "Approved evidence store",
        ),
        limitations=(
            "The matrix shown is demonstration data, not the result of a run",
            "Real extracted requirements are available in the working package instead",
            _HUMAN_REVIEW_LIMIT,
        ),
        acceptance_criteria=(
            "Unknown is a first-class state and is never silently shown as compliant",
            "Every compliance state names its source and its owner",
        ),
        route_name="compliance",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="capability_fit",
        title="Capability Fit",
        short_description=(
            "How well the organization's real, evidenced capabilities cover what "
            "the RFP demands, with gaps stated as gaps."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-D",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Governed service and product catalog",
            "Approved evidence store",
            "Named expert confirmation per capability",
        ),
        current_capabilities=(
            "Shows the intended coverage model over curated demonstration data",
            "Keeps confirmed, partial, gap, evidence-required, and unknown distinct",
        ),
        planned_capabilities=(
            "Match normalized requirements against the governed catalog",
            "Attach approved proof points and reference projects to a match",
            "Route unconfirmed matches to a named expert",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "Governed service and product catalog",
            "Approved evidence and reference-project store",
        ),
        limitations=(
            "Not built. No capability shown here is a claim about the organization.",
            "A match without confirmed evidence stays unconfirmed",
        ),
        acceptance_criteria=(
            "No capability is presented as held unless evidence is recorded for it",
            "Every unconfirmed match carries a named owner",
        ),
        route_name="capability_fit",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="competitive_intelligence",
        title="Competitive Intelligence",
        short_description=(
            "Who else is likely bidding, what they are claiming, and where the "
            "real difference lies. Demonstrated over invented competitors."
        ),
        status=FeatureStatus.DEMO,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-C",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Approved research sources and collection policy",
            "Competitor claim review by product marketing",
        ),
        current_capabilities=(
            "Demonstrates competitor monitoring and battle cards over invented data",
            "Shows collection date and confidence next to every signal",
        ),
        planned_capabilities=(
            "Collect signals from approved, attributable public sources",
            "Track claim freshness and retire stale signals",
            "Generate battle cards for review by product marketing",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "Approved public sources under a recorded collection policy",
            "Prior bid archive and recorded loss reviews",
            "Analyst input reviewed by product marketing",
        ),
        limitations=(
            "All competitors, signals, and scores shown are invented",
            "No web research is performed. Nothing is fetched from the internet.",
            "No claim here may be repeated to a customer without review",
        ),
        acceptance_criteria=(
            "Every competitor card is visibly marked as demonstration data",
            "No page element implies a running collection or a real collection date",
        ),
        route_name="competitive_intelligence",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="win_strategy",
        title="Win Strategy",
        short_description=(
            "Customer hot buttons, win themes, differentiators, and proof "
            "points, with every statement classified by how well it is backed."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.CURATED_DEMO,
        target_phase="L2-E",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Customer intelligence results",
            "Competitive intelligence results",
            "Capability fit results",
        ),
        current_capabilities=(
            "Shows the intended strategy model over curated demonstration data",
            "Classifies every statement as evidenced, inferred, or assumed",
        ),
        planned_capabilities=(
            "Derive hot buttons from extracted evaluation criteria and weights",
            "Tie each win theme to a proof point or an explicit evidence gap",
            "Record the approval that turns a draft theme into an agreed one",
        ),
        current_sources=("A curated demonstration scenario in this repository",),
        future_sources=(
            "Extracted evaluation criteria of a processed run",
            "Approved proof points and reference projects",
        ),
        limitations=(
            "Not built. No theme here is derived from a real RFP.",
            "An unbacked statement stays visibly unbacked",
            _HUMAN_REVIEW_LIMIT,
        ),
        acceptance_criteria=(
            "Every statement carries a visible evidence classification",
            "A theme without a proof point is shown as an evidence gap",
        ),
        route_name="win_strategy",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="proposal_factory",
        title="Proposal Factory",
        short_description=(
            "The intended path from reviewed requirements to a reviewable "
            "response draft, with human approval as a required step rather than "
            "an option."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.STATIC_PREVIEW,
        target_phase="L2-F",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "Governed model egress",
            "Reviewed working package",
            "Approved content and evidence store",
            "Human approval workflow",
        ),
        current_capabilities=(
            "Shows the intended stages of the response lifecycle as a static preview",
            "States, per stage, what would run and what a human must confirm",
        ),
        planned_capabilities=(
            "Build a response blueprint from reviewed requirements",
            "Draft grounded sections that cite the requirement they answer",
            "Score a draft for coverage and flag what is missing",
        ),
        current_sources=(),
        future_sources=(
            "Reviewed working package of the same bid",
            "Approved content and evidence store",
        ),
        limitations=(
            "Not built. No stage on this page runs.",
            "No autonomous agent runtime exists, and none is planned for this phase",
            _NO_MODEL_CALL,
            "No customer-facing text is generated from uploaded files",
            "Nothing reaches a customer unless a person sends it",
        ),
        acceptance_criteria=(
            "No stage can be started from the interface while the feature is planned",
            "Human approval is a required step in the modeled lifecycle",
        ),
        route_name="proposal_factory",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="review_approval",
        title="Review and Approval",
        short_description=(
            "Where a human corrects, accepts, or rejects what the system "
            "extracted, and where a bid becomes ready to submit."
        ),
        status=FeatureStatus.PLANNED,
        data_mode=DataMode.STATIC_PREVIEW,
        target_phase="L1A-S4",
        owner=_PLATFORM,
        dependencies=(
            "Review repository port",
            "Recorded reviewer identity",
            "Decision history contract",
        ),
        current_capabilities=(
            "Shows the intended review model as a static preview",
            "Demonstrates the evidence-first layout a reviewer would work in",
        ),
        planned_capabilities=(
            "Accept, reject, or request clarification per extracted item",
            "Show the source passage next to the item being reviewed",
            "Keep an append-only decision history per bid",
        ),
        current_sources=(),
        future_sources=(
            "Extraction results awaiting review",
            "Recorded review decisions",
        ),
        limitations=(
            "Not built. No control on this page changes any recorded state.",
            "The current interface can neither release nor override a gate decision",
        ),
        acceptance_criteria=(
            "No preview control performs or simulates a state change",
            "A review decision, once recorded, is never silently overwritten",
        ),
        route_name="review_approval",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="governed_llm_egress",
        title="Governed Model Egress",
        short_description=(
            "The gateway that would let BidFusion use a language model through "
            "the company's own proxy, under an explicit data-classification "
            "policy."
        ),
        status=FeatureStatus.REVIEW_REQUIRED,
        data_mode=DataMode.NOT_CONNECTED,
        target_phase="L2-A",
        owner=_SECURITY_AND_LEGAL,
        dependencies=(
            "Data-classification policy sign-off",
            "Credential handling and rotation procedure",
            "Decision on which pipeline stages may call a model",
        ),
        current_capabilities=(
            "A provider-neutral gateway port with a deterministic offline fake",
            "A settings and policy layer that is disabled unless explicitly enabled",
        ),
        planned_capabilities=(
            "Structured, schema-validated calls from named pipeline stages",
            "Per-operation data classification enforced before egress",
        ),
        current_sources=(),
        future_sources=("The company's own model proxy",),
        limitations=(
            "Not connected to the pipeline, and not reachable from this interface",
            _NO_MODEL_CALL,
            "Awaiting a governance and security review before any stage may use it",
        ),
        acceptance_criteria=(
            "The interface never constructs or reaches the gateway",
            "A disabled gateway can never reach its transport layer",
        ),
        route_name="architecture_roadmap",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="production_data_operation",
        title="Production Customer Data",
        short_description=(
            "Running real customer RFPs through BidFusion. Out of scope until a "
            "separate, explicit decision is taken."
        ),
        status=FeatureStatus.BLOCKED,
        data_mode=DataMode.NOT_CONNECTED,
        target_phase="L1B",
        owner=_SECURITY_AND_LEGAL,
        dependencies=(
            "Production security gate policy",
            "Identity and access management",
            "Retention and deletion policy",
            "Legal, privacy, and security approval",
            "Operational monitoring and support model",
        ),
        current_capabilities=(),
        planned_capabilities=("Process real customer RFPs under production controls",),
        current_sources=(),
        future_sources=("Real customer RFP packages, once approved",),
        limitations=(
            "Production customer data must not be uploaded to this build",
            "Every upload surface states its non-production scope",
            "This is a governance decision, not an engineering task",
        ),
        acceptance_criteria=(
            "No interface path accepts data described as production customer data",
            "Every upload requires an explicit non-production confirmation",
        ),
        route_name="architecture_roadmap",
        visibility=Visibility.MODULE_SECTION,
    ),
    Feature(
        key="architecture_roadmap",
        title="Architecture and Roadmap",
        short_description=(
            "The full feature record behind this interface: status, phase, "
            "dependencies, and acceptance criteria for every module."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.STATIC_PREVIEW,
        target_phase="L0.4",
        owner=_PLATFORM,
        dependencies=(),
        current_capabilities=(
            "Lists every phase with its state and where it is defined",
            "Lists every feature with its dependencies and acceptance criteria",
            "Links each feature to the page that renders it",
        ),
        planned_capabilities=("Show which acceptance criteria are covered by a test",),
        current_sources=("The BidFusion feature registry (static configuration)",),
        future_sources=(),
        limitations=(
            "Phases above Level 1 are proposed here and fixed in no architecture document",
        ),
        acceptance_criteria=(
            "Every feature and every phase in the registry is listed",
            "Proposed phases are visibly distinguished from contracted ones",
        ),
        route_name="architecture_roadmap",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="extraction_quality_evaluation",
        title="Extraction Quality",
        short_description=(
            "The frozen real-RFP evaluation of the deterministic requirement "
            "extractor: recall against a manually curated Ground Truth, "
            "coverage per document, remaining gaps, and the next step."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.STATIC_PREVIEW,
        target_phase="L1A-S6",
        owner=_PLATFORM,
        dependencies=(
            "A frozen local evaluation record, transcribed by hand into static configuration",
        ),
        current_capabilities=(
            "States strict and inclusive recall against 364 curated requirements",
            "Shows the measured progression of every extractor iteration",
            "Breaks remaining misses down by document and by failure class",
            "Names the recommended next engineering step and pilot readiness",
        ),
        planned_capabilities=(
            "Read evaluation results from a runtime evaluation store instead of "
            "transcribed configuration",
        ),
        current_sources=(
            "Frozen Evaluation #3 of extractor 0.3.0, transcribed as static configuration",
        ),
        future_sources=("A runtime evaluation harness (planned phase)",),
        limitations=(
            "Figures are a hand-frozen snapshot, not a live measurement",
            "Unmapped candidates are unreviewed; they are not proven false requirements",
            "Coverage describes the extractor, never the tender documents themselves",
        ),
        acceptance_criteria=(
            "Every figure on the page matches the frozen evaluation record",
            "No wording claims completeness or production readiness",
        ),
        route_name="extraction_quality",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="golden_knowledge_inventory",
        title="Golden Knowledge — MTD Inventory",
        short_description=(
            "The inventoried Managed Threat Detection document set: every local "
            "source with its deterministic classification, parse status, and "
            "review state. Internal knowledge pilot — local dataset, never "
            "committed to the repository."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.LOCAL_INTERNAL_PILOT,
        target_phase="GK-P1",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "A local MTD source directory, read strictly read-only",
            "The gitignored local golden knowledge runtime store",
        ),
        current_capabilities=(
            "Inventories every local MTD source file with hash-bound identity",
            "Classifies service family, technology, document type, and version "
            "deterministically from filenames — never by guessing",
            "Shows unsupported formats (PPTX) as inventoried, not parsed",
        ),
        planned_capabilities=(
            "Curated review workflow that turns extracted records into "
            "human-confirmed golden knowledge",
            "Widen ingestion beyond the pilot document families",
        ),
        current_sources=("The local golden knowledge runtime store on this machine",),
        future_sources=("A governed, reviewed golden knowledge repository",),
        limitations=(
            "The knowledge shown is machine-extracted and unverified",
            _HUMAN_REVIEW_LIMIT,
            _NO_LIVE_CONNECTOR,
            _NO_MODEL_CALL,
            "Parsers are reviewed against synthetic fixtures, not certified "
            "for hostile production input",
        ),
        acceptance_criteria=(
            "Every file of the local dataset appears in the inventory",
            "No absolute local path is rendered or serialized",
            "Unsupported formats stay visible with their status",
        ),
        route_name="golden_knowledge",
        visibility=Visibility.PRIMARY_NAV,
    ),
    Feature(
        key="golden_capability_matching",
        title="Capability Matching (Pilot)",
        short_description=(
            "Five synthetic demo requirements matched deterministically against "
            "rule-extracted, unverified MTD capability claims with their "
            "evidence sources."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.LOCAL_INTERNAL_PILOT,
        target_phase="GK-P1",
        owner=_BID_MANAGEMENT,
        dependencies=("Capability claims extracted into the local golden knowledge store",),
        current_capabilities=(
            "Matches by fixed capability tokens — no embeddings, no model",
            "Keeps matched, partial, unknown, gap, and evidence-required distinct",
            "Names the evidence sources behind every match",
        ),
        planned_capabilities=(
            "Match reviewed RFP requirements once the golden knowledge is human-confirmed",
        ),
        current_sources=("The local golden knowledge runtime store on this machine",),
        future_sources=("Reviewed requirements from the RFP intelligence lane",),
        limitations=(
            "The requirements shown are synthetic demo inputs, not customer RFPs",
            "Claims are extracted and unverified; a match confirms nothing",
            _HUMAN_REVIEW_LIMIT,
            _NO_MODEL_CALL,
        ),
        acceptance_criteria=(
            "Every match states its status and its human review requirement",
            "Synthetic inputs are labeled as synthetic wherever they appear",
        ),
        route_name="golden_matching",
        visibility=Visibility.MODULE_PAGE,
    ),
    Feature(
        key="requirement_knowledge_assessment",
        title="Requirement Knowledge Assessment",
        short_description=(
            "Extracted RFP requirements from a completed synthetic run, "
            "deterministically normalized and matched as candidates against "
            "the golden knowledge pilot, with evidence and mandatory human "
            "review."
        ),
        status=FeatureStatus.LIVE,
        data_mode=DataMode.LOCAL_INTERNAL_PILOT,
        target_phase="GK-P1",
        owner=_BID_MANAGEMENT,
        dependencies=(
            "A completed synthetic pipeline run with extracted requirements",
            "Capability claims in the local golden knowledge runtime store",
        ),
        current_capabilities=(
            "Converts extracted requirements into golden requirement candidates "
            "deterministically — no model, no embeddings",
            "Detects negative or excluding requirement language and never turns "
            "it into a positive candidate match",
            "Shows candidate match status, matched capability, claim status, "
            "and the evidence sources behind every candidate",
            "Keeps RFP provenance and golden evidence provenance separate",
            "Records immutable, versioned human review decisions per assessment "
            "— confirm, reject, or needs clarification — bound to the exact "
            "assessment content reviewed",
        ),
        planned_capabilities=("Assessment over reviewed, human-confirmed golden knowledge",),
        current_sources=(
            "Requirement artifacts of a completed synthetic run",
            "The local golden knowledge runtime store on this machine",
        ),
        future_sources=("A governed, reviewed golden knowledge repository",),
        limitations=(
            "The RFP input is a synthetic fixture package, never a customer RFP",
            "Claims are machine-extracted and unverified; a candidate match confirms nothing",
            _HUMAN_REVIEW_LIMIT,
            _NO_MODEL_CALL,
            "An absent or damaged golden store means not evaluated, never a gap",
        ),
        acceptance_criteria=(
            "Every assessment states its human review requirement",
            "A negative or excluded requirement never produces a positive candidate match",
            "A missing golden store renders a safe not-evaluated state",
            "A bid review decision never changes a golden claim",
        ),
        route_name="show_knowledge_assessment",
        visibility=Visibility.MODULE_SECTION,
    ),
)


_PHASES_BY_ID = {phase.phase_id: phase for phase in PHASES}
_FEATURES_BY_KEY = {feature.key: feature for feature in FEATURES}


def _validate_registry() -> None:
    """Fail at import time rather than render a registry that lies.

    A malformed registry is a programming error, not a runtime condition:
    the UI has no meaningful fallback for a feature whose phase does not
    exist or whose key is duplicated, so it never starts with one.
    """
    if len(_PHASES_BY_ID) != len(PHASES):
        msg = "duplicate phase_id in PHASES"
        raise ValueError(msg)
    if len(_FEATURES_BY_KEY) != len(FEATURES):
        msg = "duplicate feature key in FEATURES"
        raise ValueError(msg)
    for feature in FEATURES:
        if feature.target_phase not in _PHASES_BY_ID:
            msg = f"feature {feature.key} targets unknown phase {feature.target_phase}"
            raise ValueError(msg)


_validate_registry()


def all_features() -> tuple[Feature, ...]:
    """Every registered feature, in registry order."""
    return FEATURES


def all_phases() -> tuple[Phase, ...]:
    """Every delivery phase, in order."""
    return PHASES


def feature(key: str) -> Feature | None:
    """The feature registered under ``key``, or ``None``."""
    return _FEATURES_BY_KEY.get(key)


def phase(phase_id: str) -> Phase | None:
    """The phase registered under ``phase_id``, or ``None``."""
    return _PHASES_BY_ID.get(phase_id)


def feature_for_route(route_name: str) -> Feature | None:
    """The first feature whose own page is rendered by ``route_name``.

    Section-level features share their page with the module that owns it,
    so page-level visibilities win: a run page reports the run, not one
    of the sections drawn on it.
    """
    for wanted in (Visibility.PRIMARY_NAV, Visibility.MODULE_PAGE, Visibility.MODULE_SECTION):
        for candidate in FEATURES:
            if candidate.route_name == route_name and candidate.visibility is wanted:
                return candidate
    return None


def features_for_phase(phase_id: str) -> tuple[Feature, ...]:
    """Every feature targeting one phase, in registry order."""
    return tuple(item for item in FEATURES if item.target_phase == phase_id)
