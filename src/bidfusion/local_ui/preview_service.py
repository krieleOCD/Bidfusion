"""Application service for the preview surfaces.

The one place that puts a feature record and a demonstration scenario
together into what a page needs. It imports no connector, no security
service, no pipeline, and no model gateway — a preview page cannot reach
any of them, by construction rather than by discipline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bidfusion.local_ui import preview_viewmodels as vm
from bidfusion.local_ui import scenario_registry
from bidfusion.local_ui.feature_registry import Feature
from bidfusion.local_ui.preview_schemas import Scenario
from bidfusion.local_ui.product_shell import FeatureDetailView, feature_detail_view


@dataclass(frozen=True, slots=True)
class PreviewPage:
    """What every preview page gets: its own record and its scenario."""

    detail: FeatureDetailView
    header: vm.ScenarioHeader


def scenario_choices() -> tuple[tuple[str, str], ...]:
    """Every offered scenario as (key, title), in display order."""
    return tuple((scenario.key, scenario.title) for scenario in scenario_registry.all_scenarios())


def resolve_scenario_key(requested: str | None) -> str | None:
    """The scenario a request asked for, the default, or ``None``.

    No parameter means the default scenario. A parameter that names no
    offered scenario yields ``None`` so the caller can refuse: quietly
    showing a different scenario than the one that was asked for would
    misrepresent whatever the reader was linked to.
    """
    if requested is None:
        return scenario_registry.DEFAULT_SCENARIO_KEY
    if requested not in scenario_registry.available_keys():
        return None
    return requested


def load_page(item: Feature, scenario_key: str) -> tuple[PreviewPage, Scenario]:
    """The shared page context plus the scenario its sections come from."""
    scenario = scenario_registry.load_scenario(scenario_key)
    page = PreviewPage(
        detail=feature_detail_view(item),
        header=vm.scenario_header(scenario, scenario_choices()),
    )
    return page, scenario


def customer_intelligence(scenario: Scenario) -> vm.CustomerIntelligenceView:
    return vm.customer_intelligence_view(scenario.customer_intelligence)


def compliance(scenario: Scenario) -> vm.ComplianceView:
    return vm.compliance_view(scenario.compliance)


def capability_fit(scenario: Scenario) -> vm.CapabilityFitView:
    return vm.capability_fit_view(scenario.capability_fit)


def qualification(scenario: Scenario) -> vm.QualificationView:
    return vm.qualification_view(scenario.qualification)


def competitive_intelligence(
    scenario: Scenario, competitor_key: str | None
) -> vm.CompetitiveIntelligenceView:
    return vm.competitive_intelligence_view(scenario.competitive_intelligence, competitor_key)


def win_strategy(scenario: Scenario) -> vm.WinStrategyView:
    return vm.win_strategy_view(scenario.win_strategy)


def review_approval(scenario: Scenario) -> vm.ReviewApprovalView:
    return vm.review_approval_view(scenario.review_approval)


def response_lifecycle() -> vm.ResponseLifecycleView:
    """The intended response lifecycle. Product structure, not scenario data."""
    return vm.response_lifecycle_view(scenario_registry.load_response_lifecycle())


#: Which view model each preview page renders. Keyed by feature so a
#: route never has to branch on what it is showing, and so a page can
#: only ever receive the section its own feature declares.
_SECTION_BUILDERS: dict[str, Callable[[Scenario, str | None], object]] = {
    "customer_intelligence": lambda scenario, _focus: customer_intelligence(scenario),
    "compliance": lambda scenario, _focus: compliance(scenario),
    "capability_fit": lambda scenario, _focus: capability_fit(scenario),
    "qualification": lambda scenario, _focus: qualification(scenario),
    "competitive_intelligence": competitive_intelligence,
    "win_strategy": lambda scenario, _focus: win_strategy(scenario),
    "review_approval": lambda scenario, _focus: review_approval(scenario),
    "proposal_factory": lambda _scenario, _focus: response_lifecycle(),
}


def section_for(feature_key: str, scenario: Scenario, focus: str | None) -> object:
    """The view model one preview page renders.

    Raises :class:`KeyError` for a feature that declares no section; the
    caller registers only features that have one, so reaching that would
    be a wiring mistake rather than a request.
    """
    return _SECTION_BUILDERS[feature_key](scenario, focus)
