"""The product shell: navigation and the status context every page carries.

One place decides how a registry status becomes something a person can
read, so no template ever spells out a status of its own. This module
projects :mod:`bidfusion.local_ui.feature_registry` into display
structures and knows which endpoint belongs to which part of the
product. It performs no I/O, imports no Flask, and reaches no service.
"""

from __future__ import annotations

from dataclasses import dataclass

from bidfusion.local_ui.feature_registry import (
    DataMode,
    Feature,
    FeatureStatus,
    Phase,
    PhaseDefinition,
    PhaseState,
    Visibility,
    all_features,
    feature_for_route,
)
from bidfusion.local_ui.feature_registry import (
    phase as phase_by_id,
)
from bidfusion.local_ui.viewmodels import StatusDisplay

PRODUCT_NAME = "BidFusion"
ORGANIZATION_NAME = "Orange Cyberdefense"

#: Shown next to the wordmark on every page. This build is an internal
#: preview of a Level 1A (authorized non-production test data) system —
#: never a production surface, and it must never imply otherwise.
PREVIEW_LABEL = "Internal Product Preview"
STAGE_LABEL = "Level 1A"

_STATUS_DISPLAY: dict[FeatureStatus, tuple[str, str]] = {
    FeatureStatus.LIVE: ("success", "check"),
    FeatureStatus.DEMO: ("info", "info"),
    FeatureStatus.PLANNED: ("neutral", "clock"),
    FeatureStatus.BLOCKED: ("danger", "octagon-x"),
    FeatureStatus.REVIEW_REQUIRED: ("warning", "alert"),
}

_DATA_MODE_DISPLAY: dict[DataMode, tuple[str, str]] = {
    DataMode.VERIFIED_ARTIFACTS: ("success", "shield"),
    DataMode.SYNTHETIC_FIXTURE: ("neutral", "file"),
    DataMode.CURATED_DEMO: ("warning", "info"),
    DataMode.STATIC_PREVIEW: ("neutral", "minus"),
    DataMode.NOT_CONNECTED: ("neutral", "unlink"),
    DataMode.LOCAL_INTERNAL_PILOT: ("warning", "layers"),
}

_PHASE_STATE_DISPLAY: dict[PhaseState, tuple[str, str]] = {
    PhaseState.DELIVERED: ("success", "check"),
    PhaseState.NEXT: ("info", "arrow-right"),
    PhaseState.PLANNED: ("neutral", "clock"),
    PhaseState.BLOCKED: ("danger", "octagon-x"),
}

#: Human-readable status labels. Registry values are machine-shaped;
#: these are what a reader sees next to the icon.
_STATUS_LABEL: dict[FeatureStatus, str] = {
    FeatureStatus.LIVE: "LIVE",
    FeatureStatus.DEMO: "DEMO",
    FeatureStatus.PLANNED: "PLANNED",
    FeatureStatus.BLOCKED: "BLOCKED",
    FeatureStatus.REVIEW_REQUIRED: "REVIEW REQUIRED",
}

_DATA_MODE_LABEL: dict[DataMode, str] = {
    DataMode.VERIFIED_ARTIFACTS: "VERIFIED ARTIFACTS",
    DataMode.SYNTHETIC_FIXTURE: "SYNTHETIC FIXTURE",
    DataMode.CURATED_DEMO: "CURATED DEMO",
    DataMode.STATIC_PREVIEW: "STATIC PREVIEW",
    DataMode.NOT_CONNECTED: "NOT CONNECTED",
    DataMode.LOCAL_INTERNAL_PILOT: "LOCAL INTERNAL PILOT",
}

#: What a reader has to understand about a surface before trusting what
#: it shows. Derived from the status, never written into a template.
_REVIEW_NOTE: dict[FeatureStatus, str] = {
    FeatureStatus.LIVE: (
        "Everything shown is read from recorded pipeline artifacts. "
        "Bid decisions stay with the bid team."
    ),
    FeatureStatus.DEMO: (
        "Demonstration data. Nothing on this page describes a real customer, "
        "competitor, or opportunity."
    ),
    FeatureStatus.PLANNED: (
        "Preview of a planned surface. No control on this page changes any recorded state."
    ),
    FeatureStatus.BLOCKED: (
        "Blocked pending an explicit decision outside engineering. Not available in this build."
    ),
    FeatureStatus.REVIEW_REQUIRED: (
        "Built but not connected. Awaiting a governance and security review "
        "before any part of the product may use it."
    ),
}

#: Plain-language meaning of each status and data mode, for the legend
#: on the overview. One wording, used everywhere it is explained.
_STATUS_MEANING: dict[FeatureStatus, str] = {
    FeatureStatus.LIVE: "Built and running here. What it shows, it actually did.",
    FeatureStatus.DEMO: (
        "Built as a demonstration. The behaviour is real, the data underneath is invented."
    ),
    FeatureStatus.PLANNED: (
        "Not built. The page shows the intended information model and nothing more."
    ),
    FeatureStatus.BLOCKED: "Waiting on a decision outside engineering before work can start.",
    FeatureStatus.REVIEW_REQUIRED: (
        "Built, but deliberately left disconnected until a governance or security review clears it."
    ),
}

_DATA_MODE_MEANING: dict[DataMode, str] = {
    DataMode.VERIFIED_ARTIFACTS: (
        "Versioned artifacts of a real run, re-verified against their integrity manifest."
    ),
    DataMode.SYNTHETIC_FIXTURE: (
        "The repository's own generated fixture packages, processed for real."
    ),
    DataMode.CURATED_DEMO: (
        "Hand-authored demonstration data. No real customer, competitor, or colleague."
    ),
    DataMode.STATIC_PREVIEW: "Layout and structure only. There is no data source behind it.",
    DataMode.NOT_CONNECTED: "Nothing is wired up. No system is contacted.",
    DataMode.LOCAL_INTERNAL_PILOT: (
        "A local, gitignored store derived from real internal documents on this "
        "machine. Machine-extracted, unverified, and never committed."
    ),
}

_NO_SOURCE = "Not connected"


@dataclass(frozen=True, slots=True)
class NavItem:
    """One entry in a world's sub-navigation."""

    key: str
    label: str
    endpoint: str
    feature_key: str


@dataclass(frozen=True, slots=True)
class NavWorld:
    """One top-level area of the product and the pages inside it.

    ``group`` separates the operational workspace ("workspace") — the
    places a person working on one bid actually goes — from the internal
    surfaces ("internal"): the product roadmap and the future-capability
    previews. The internal group renders quieter, so someone working a
    bid is not constantly steered toward future-feature material.
    """

    key: str
    label: str
    endpoint: str
    feature_key: str
    items: tuple[NavItem, ...]
    member_endpoints: tuple[str, ...]
    group: str = "workspace"
    icon: str = "file"


#: The product navigation. The operational workspace mirrors the actual
#: functional loop — understand the RFP, hold the knowledge and its
#: evidence — while roadmap and future-capability previews step back
#: into a separate internal group.
NAV_WORLDS: tuple[NavWorld, ...] = (
    NavWorld(
        key="bids",
        label="Bids",
        endpoint="index",
        feature_key="rfp_intake",
        items=(
            NavItem(
                key="intake", label="Intake and Runs", endpoint="index", feature_key="rfp_intake"
            ),
            NavItem(
                key="compliance",
                label="Compliance",
                endpoint="compliance",
                feature_key="compliance",
            ),
            NavItem(
                key="capability_fit",
                label="Capability Fit",
                endpoint="capability_fit",
                feature_key="capability_fit",
            ),
            NavItem(
                key="qualification",
                label="Qualification",
                endpoint="qualification",
                feature_key="qualification",
            ),
            NavItem(
                key="factory",
                label="Proposal",
                endpoint="proposal_factory",
                feature_key="proposal_factory",
            ),
            NavItem(
                key="review_approval",
                label="Review",
                endpoint="review_approval",
                feature_key="review_approval",
            ),
        ),
        member_endpoints=(
            "show_run",
            "show_working_package",
            "show_review_package",
            "show_knowledge_assessment",
            "show_upload",
        ),
        icon="target",
    ),
    NavWorld(
        key="golden",
        label="Knowledge",
        endpoint="golden_knowledge",
        feature_key="golden_knowledge_inventory",
        items=(
            NavItem(
                key="inventory",
                label="MTD Inventory",
                endpoint="golden_knowledge",
                feature_key="golden_knowledge_inventory",
            ),
            NavItem(
                key="matching",
                label="Capability Matching",
                endpoint="golden_matching",
                feature_key="golden_capability_matching",
            ),
        ),
        member_endpoints=(),
        icon="layers",
    ),
    NavWorld(
        key="portfolio",
        label="Portfolio and Strategy",
        endpoint="competitive_intelligence",
        feature_key="competitive_intelligence",
        items=(
            NavItem(
                key="competitors",
                label="Competitors",
                endpoint="competitive_intelligence",
                feature_key="competitive_intelligence",
            ),
            NavItem(
                key="customer_intelligence",
                label="Customer Intelligence",
                endpoint="customer_intelligence",
                feature_key="customer_intelligence",
            ),
            NavItem(
                key="win_strategy",
                label="Win Strategy",
                endpoint="win_strategy",
                feature_key="win_strategy",
            ),
        ),
        member_endpoints=(),
        icon="users",
    ),
    NavWorld(
        key="product",
        label="Product Status",
        endpoint="overview",
        feature_key="product_overview",
        items=(
            NavItem(
                key="operating_model",
                label="Operating Model",
                endpoint="overview",
                feature_key="product_overview",
            ),
            NavItem(
                key="extraction_quality",
                label="Extraction Quality",
                endpoint="extraction_quality",
                feature_key="extraction_quality_evaluation",
            ),
            NavItem(
                key="roadmap",
                label="Architecture and Roadmap",
                endpoint="architecture_roadmap",
                feature_key="architecture_roadmap",
            ),
        ),
        member_endpoints=("feature_detail",),
        group="internal",
        icon="map",
    ),
)


@dataclass(frozen=True, slots=True)
class NavItemView:
    """One navigation entry, ready to render.

    The status travels as a plain word, not as a toned badge: a green
    badge in the navigation of, say, a quarantine page would read as a
    statement about that page rather than about the module it links to.
    Each page states its own status in the feature strip below the
    navigation, where it cannot be mistaken for anything else.
    """

    key: str
    label: str
    endpoint: str
    status_label: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class NavWorldView:
    """One top-level navigation entry, ready to render.

    ``is_internal`` marks the roadmap and future-capability areas, which
    the navigation renders visually quieter than the working areas.
    """

    key: str
    label: str
    endpoint: str
    is_active: bool
    is_internal: bool
    icon: str


@dataclass(frozen=True, slots=True)
class FeatureStatusView:
    """The status context a page must state about itself, in plain sight."""

    key: str
    title: str
    short_description: str
    status: StatusDisplay
    data_mode: StatusDisplay
    phase_id: str
    phase_title: str
    phase_state: StatusDisplay
    phase_is_proposed: bool
    current_source: str
    review_note: str
    notice_tone: str
    """Banner tone for this feature's notice. Decided here, not in a template."""


@dataclass(frozen=True, slots=True)
class ShellContext:
    """Everything the shared layout needs, for any page."""

    product_name: str
    organization_name: str
    preview_label: str
    stage_label: str
    worlds: tuple[NavWorldView, ...]
    sub_nav: tuple[NavItemView, ...]
    active_world_key: str | None
    feature_status: FeatureStatusView | None


def status_display(status: FeatureStatus) -> StatusDisplay:
    """One feature status as label plus non-color signals."""
    tone, icon_name = _STATUS_DISPLAY[status]
    return StatusDisplay(label=_STATUS_LABEL[status], tone=tone, icon=icon_name)


def data_mode_display(data_mode: DataMode) -> StatusDisplay:
    """One data mode as label plus non-color signals."""
    tone, icon_name = _DATA_MODE_DISPLAY[data_mode]
    return StatusDisplay(label=_DATA_MODE_LABEL[data_mode], tone=tone, icon=icon_name)


def phase_state_display(state: PhaseState) -> StatusDisplay:
    """One phase state as label plus non-color signals."""
    tone, icon_name = _PHASE_STATE_DISPLAY[state]
    return StatusDisplay(label=state.value, tone=tone, icon=icon_name)


def status_legend() -> tuple[tuple[StatusDisplay, str], ...]:
    """Every feature status with its plain-language meaning."""
    return tuple((status_display(status), meaning) for status, meaning in _STATUS_MEANING.items())


def data_mode_legend() -> tuple[tuple[StatusDisplay, str], ...]:
    """Every data mode with its plain-language meaning."""
    return tuple((data_mode_display(mode), meaning) for mode, meaning in _DATA_MODE_MEANING.items())


def feature_status_view(item: Feature) -> FeatureStatusView:
    """The status context for one feature."""
    target = phase_by_id(item.target_phase)
    if target is None:  # pragma: no cover - the registry validates this at import
        msg = f"feature {item.key} targets unknown phase {item.target_phase}"
        raise ValueError(msg)
    return FeatureStatusView(
        key=item.key,
        title=item.title,
        short_description=item.short_description,
        status=status_display(item.status),
        data_mode=data_mode_display(item.data_mode),
        phase_id=target.phase_id,
        phase_title=target.title,
        phase_state=phase_state_display(target.state),
        phase_is_proposed=target.definition is PhaseDefinition.PROPOSED,
        current_source=item.current_sources[0] if item.current_sources else _NO_SOURCE,
        review_note=_REVIEW_NOTE[item.status],
        notice_tone="info" if item.status is FeatureStatus.LIVE else "warning",
    )


def world_for_endpoint(endpoint: str | None) -> NavWorld | None:
    """The world one endpoint belongs to, or ``None`` for unknown pages."""
    if endpoint is None:
        return None
    for world in NAV_WORLDS:
        if endpoint == world.endpoint or endpoint in world.member_endpoints:
            return world
        if any(item.endpoint == endpoint for item in world.items):
            return world
    return None


def build_shell_context(endpoint: str | None) -> ShellContext:
    """The shared layout context for whichever page is being rendered.

    Unknown endpoints — error pages, static files — still get a complete
    shell with no active world, so navigation never disappears when
    something goes wrong.
    """
    active_world = world_for_endpoint(endpoint)
    worlds = tuple(
        NavWorldView(
            key=world.key,
            label=world.label,
            endpoint=world.endpoint,
            is_active=active_world is not None and world.key == active_world.key,
            is_internal=world.group == "internal",
            icon=world.icon,
        )
        for world in NAV_WORLDS
    )
    sub_nav: tuple[NavItemView, ...] = ()
    if active_world is not None:
        sub_nav = tuple(
            NavItemView(
                key=item.key,
                label=item.label,
                endpoint=item.endpoint,
                status_label=_STATUS_LABEL[_feature_status_of(item.feature_key)],
                is_active=item.endpoint == endpoint,
            )
            for item in active_world.items
        )
    current = feature_for_route(endpoint) if endpoint is not None else None
    return ShellContext(
        product_name=PRODUCT_NAME,
        organization_name=ORGANIZATION_NAME,
        preview_label=PREVIEW_LABEL,
        stage_label=STAGE_LABEL,
        worlds=worlds,
        sub_nav=sub_nav,
        active_world_key=active_world.key if active_world is not None else None,
        feature_status=feature_status_view(current) if current is not None else None,
    )


@dataclass(frozen=True, slots=True)
class ModuleCardView:
    """One product module on the overview, as a card."""

    key: str
    title: str
    short_description: str
    status: StatusDisplay
    data_mode: StatusDisplay
    phase_id: str
    phase_title: str
    endpoint: str
    has_page: bool


@dataclass(frozen=True, slots=True)
class ModuleGroupView:
    """Modules sharing one status, so the overview separates real from planned."""

    key: str
    title: str
    summary: str
    modules: tuple[ModuleCardView, ...]


_GROUP_ORDER: tuple[tuple[FeatureStatus, str, str], ...] = (
    (
        FeatureStatus.LIVE,
        "Implemented",
        "Built and running in this build. What you see is what the system did.",
    ),
    (
        FeatureStatus.DEMO,
        "Demonstrated",
        "Built as a demonstration over curated, invented data. Not a real result.",
    ),
    (
        FeatureStatus.REVIEW_REQUIRED,
        "Awaiting review",
        "Built, but deliberately not connected until a review clears it.",
    ),
    (
        FeatureStatus.PLANNED,
        "Planned",
        "Not built. These pages show the intended model so it can be argued with early.",
    ),
    (
        FeatureStatus.BLOCKED,
        "Blocked",
        "Waiting on a decision outside engineering.",
    ),
)

#: Section-level features are described on the page that owns them, so
#: the overview lists the pages a reader can actually open.
_OVERVIEW_VISIBILITIES = (Visibility.PRIMARY_NAV, Visibility.MODULE_PAGE)


def module_groups() -> tuple[ModuleGroupView, ...]:
    """Every module the overview lists, grouped by how real it is."""
    groups: list[ModuleGroupView] = []
    for status, title, summary in _GROUP_ORDER:
        modules = tuple(
            _module_card(item)
            for item in all_features()
            if item.status is status and item.visibility in _OVERVIEW_VISIBILITIES
        )
        if modules:
            groups.append(
                ModuleGroupView(
                    key=status.value.lower(), title=title, summary=summary, modules=modules
                )
            )
    return tuple(groups)


def _module_card(item: Feature) -> ModuleCardView:
    target = phase_by_id(item.target_phase)
    if target is None:  # pragma: no cover - the registry validates this at import
        msg = f"feature {item.key} targets unknown phase {item.target_phase}"
        raise ValueError(msg)
    return ModuleCardView(
        key=item.key,
        title=item.title,
        short_description=item.short_description,
        status=status_display(item.status),
        data_mode=data_mode_display(item.data_mode),
        phase_id=target.phase_id,
        phase_title=target.title,
        endpoint=item.route_name,
        has_page=item.visibility in _OVERVIEW_VISIBILITIES,
    )


#: Endpoints that only exist inside one run or one upload. Nothing can
#: link to them without that context, so feature records name them
#: without offering a link.
CONTEXTUAL_ENDPOINTS = frozenset(
    {
        "show_run",
        "show_working_package",
        "show_review_package",
        "show_knowledge_assessment",
        "show_upload",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """One thing BidFusion does — or intends to do — with an RFP package."""

    key: str
    title: str
    status: StatusDisplay
    phase_id: str
    endpoint: str | None


#: What happens to an RFP package, in the order it happens. Rendered on
#: the intake page as the honest counterpart to a feature list: every
#: entry carries the status the registry records for it.
RFP_LIFECYCLE_FEATURES: tuple[str, ...] = (
    "rfp_intake",
    "package_security_gate",
    "upload_security_review",
    "synthetic_analysis",
    "working_package",
    "quality_review_package",
    "review_approval",
    "compliance",
    "capability_fit",
    "qualification",
    "customer_intelligence",
    "competitive_intelligence",
    "win_strategy",
    "proposal_factory",
)


def capability_rows(feature_keys: tuple[str, ...]) -> tuple[CapabilityRow, ...]:
    """The named features as a compact, status-bearing list."""
    by_key = {item.key: item for item in all_features()}
    rows: list[CapabilityRow] = []
    for key in feature_keys:
        item = by_key.get(key)
        if item is None:
            msg = f"unknown feature key {key}"
            raise ValueError(msg)
        rows.append(
            CapabilityRow(
                key=item.key,
                title=item.title,
                status=status_display(item.status),
                phase_id=item.target_phase,
                endpoint=(
                    None
                    if item.route_name in CONTEXTUAL_ENDPOINTS
                    or item.visibility is Visibility.MODULE_SECTION
                    else item.route_name
                ),
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class FeatureDetailView:
    """One complete feature record, as the roadmap and detail page show it."""

    status: FeatureStatusView
    owner: str
    visibility: str
    route_name: str
    page_endpoint: str | None
    dependencies: tuple[str, ...]
    current_capabilities: tuple[str, ...]
    planned_capabilities: tuple[str, ...]
    current_sources: tuple[str, ...]
    future_sources: tuple[str, ...]
    limitations: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    phase_summary: str
    phase_definition_reference: str


def feature_detail_view(item: Feature) -> FeatureDetailView:
    """Everything the registry records about one feature, ready to render."""
    target = phase_by_id(item.target_phase)
    if target is None:  # pragma: no cover - the registry validates this at import
        msg = f"feature {item.key} targets unknown phase {item.target_phase}"
        raise ValueError(msg)
    return FeatureDetailView(
        status=feature_status_view(item),
        owner=item.owner,
        visibility=item.visibility.value,
        route_name=item.route_name,
        page_endpoint=None if item.route_name in CONTEXTUAL_ENDPOINTS else item.route_name,
        dependencies=item.dependencies,
        current_capabilities=item.current_capabilities,
        planned_capabilities=item.planned_capabilities,
        current_sources=item.current_sources,
        future_sources=item.future_sources,
        limitations=item.limitations,
        acceptance_criteria=item.acceptance_criteria,
        phase_summary=target.summary,
        phase_definition_reference=target.definition_reference,
    )


@dataclass(frozen=True, slots=True)
class PhaseView:
    """One delivery phase with the features it carries."""

    phase_id: str
    title: str
    summary: str
    state: StatusDisplay
    is_proposed: bool
    definition_reference: str
    features: tuple[ModuleCardView, ...]


def phase_views(phases: tuple[Phase, ...], features: tuple[Feature, ...]) -> tuple[PhaseView, ...]:
    """Every phase with its features attached, in phase order."""
    return tuple(
        PhaseView(
            phase_id=item.phase_id,
            title=item.title,
            summary=item.summary,
            state=phase_state_display(item.state),
            is_proposed=item.definition is PhaseDefinition.PROPOSED,
            definition_reference=item.definition_reference,
            features=tuple(
                _module_card(owned) for owned in features if owned.target_phase == item.phase_id
            ),
        )
        for item in phases
    )


def _feature_status_of(feature_key: str) -> FeatureStatus:
    for item in all_features():
        if item.key == feature_key:
            return item.status
    msg = f"navigation references unknown feature {feature_key}"
    raise ValueError(msg)
