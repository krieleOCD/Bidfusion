"""Display projections of the demonstration scenarios.

Templates never see a scenario model, only the structures built here.
That keeps two properties worth having: a page cannot reach into data it
was not given, and every state a reader sees carries its icon and its
word alongside its color, decided in one place rather than per template.

Nothing here reads a file or knows about Flask. It converts validated
scenario data into things a template can render, and no more.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from bidfusion.local_ui.preview_schemas import (
    AssessmentVerdict,
    BattleCard,
    CapabilityFit,
    CompetitiveIntelligence,
    Competitor,
    Compliance,
    ComplianceState,
    ConnectionState,
    CoverageState,
    CustomerIntelligence,
    EvidenceClass,
    FactorVerdict,
    Qualification,
    ResponseLifecycle,
    ReviewApproval,
    ReviewState,
    Scenario,
    ThreatBand,
    WinStrategy,
)
from bidfusion.local_ui.viewmodels import StatusDisplay

#: Coarse bands are rendered as fixed CSS steps, never as an inline
#: width: the page's Content-Security-Policy forbids inline styles, and
#: a five-step band is a more honest shape for demonstration data than a
#: percentage would be.
METER_STEPS = 5

_CONNECTION: dict[ConnectionState, tuple[str, str]] = {
    ConnectionState.NOT_CONNECTED: ("neutral", "unlink"),
    ConnectionState.CONNECTED: ("success", "check"),
}

_EVIDENCE: dict[EvidenceClass, tuple[str, str]] = {
    EvidenceClass.EVIDENCE_BACKED: ("success", "file"),
    EvidenceClass.HUMAN_CONFIRMED: ("success", "check"),
    EvidenceClass.MODEL_INFERENCE: ("info", "info"),
    EvidenceClass.ASSUMPTION: ("warning", "alert"),
    EvidenceClass.DEMO: ("neutral", "info"),
}

_COMPLIANCE: dict[ComplianceState, tuple[str, str]] = {
    ComplianceState.COMPLIANT: ("success", "check"),
    ComplianceState.PARTIALLY_COMPLIANT: ("warning", "alert"),
    ComplianceState.NOT_COMPLIANT: ("danger", "x"),
    ComplianceState.CLARIFICATION_REQUIRED: ("warning", "info"),
    ComplianceState.EVIDENCE_REQUIRED: ("warning", "file"),
    ComplianceState.UNKNOWN: ("neutral", "minus"),
}

_COVERAGE: dict[CoverageState, tuple[str, str]] = {
    CoverageState.CONFIRMED: ("success", "check"),
    CoverageState.PARTIAL: ("warning", "alert"),
    CoverageState.GAP: ("danger", "x"),
    CoverageState.EVIDENCE_REQUIRED: ("warning", "file"),
    CoverageState.UNKNOWN: ("neutral", "minus"),
}

#: What each coverage state means, in one place rather than repeated in
#: a template's legend where it could drift from the schema.
_COVERAGE_MEANING: dict[CoverageState, str] = {
    CoverageState.CONFIRMED: "Covered by a catalogued service, with evidence recorded.",
    CoverageState.PARTIAL: (
        "Partly covered. What is missing has to be stated in the response, not glossed."
    ),
    CoverageState.EVIDENCE_REQUIRED: (
        "Probably covered, but nothing approved exists yet to prove it."
    ),
    CoverageState.GAP: (
        "Nothing in the portfolio covers it. A partner, or a decision not to bid it."
    ),
    CoverageState.UNKNOWN: "Nobody has assessed it. Never shown as covered.",
}

_FACTOR: dict[FactorVerdict, tuple[str, str]] = {
    FactorVerdict.STRONG: ("success", "check"),
    FactorVerdict.ADEQUATE: ("info", "info"),
    FactorVerdict.WEAK: ("danger", "alert"),
    FactorVerdict.UNKNOWN: ("neutral", "minus"),
}

_ASSESSMENT: dict[AssessmentVerdict, tuple[str, str]] = {
    AssessmentVerdict.GO: ("success", "check"),
    AssessmentVerdict.GO_WITH_CONDITIONS: ("warning", "alert"),
    AssessmentVerdict.REVIEW_REQUIRED: ("warning", "alert"),
    AssessmentVerdict.NO_GO: ("danger", "octagon-x"),
}

_THREAT: dict[ThreatBand, tuple[str, str]] = {
    ThreatBand.HIGH: ("danger", "alert"),
    ThreatBand.MEDIUM: ("warning", "info"),
    ThreatBand.LOW: ("neutral", "minus"),
}

_REVIEW: dict[ReviewState, tuple[str, str]] = {
    ReviewState.AWAITING_REVIEW: ("warning", "clock"),
    ReviewState.ACCEPTED: ("success", "check"),
    ReviewState.REJECTED: ("danger", "x"),
    ReviewState.CLARIFICATION_REQUESTED: ("warning", "info"),
}


def _chip[StateT: StrEnum](
    value: StateT, mapping: Mapping[StateT, tuple[str, str]]
) -> StatusDisplay:
    """One state as its word, its icon, and its tone.

    The mapping is keyed by the state's own type, so a new member of any
    of these vocabularies fails type checking here until it has been
    given a way to be displayed.
    """
    tone, icon_name = mapping[value]
    return StatusDisplay(label=value.value.replace("_", " "), tone=tone, icon=icon_name)


@dataclass(frozen=True, slots=True)
class Meter:
    """One coarse band, as a step count plus the words to read it by."""

    level: int
    steps: int
    label: str


def _meter(level: int, caption: str) -> Meter:
    return Meter(level=level, steps=METER_STEPS, label=f"{caption}: {level} of {METER_STEPS}")


@dataclass(frozen=True, slots=True)
class ScenarioChoice:
    """One selectable demonstration scenario."""

    key: str
    title: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class TimelineRow:
    """One dated milestone."""

    label: str
    date: str
    note: str
    is_critical: bool


@dataclass(frozen=True, slots=True)
class ScenarioHeader:
    """The opportunity a preview page is showing, and which one it is."""

    key: str
    title: str
    summary: str
    notice: str
    customer: str
    sector: str
    region: str
    scope: str
    volume_band: str
    timeline: tuple[TimelineRow, ...]
    choices: tuple[ScenarioChoice, ...]


def scenario_header(scenario: Scenario, choices: tuple[tuple[str, str], ...]) -> ScenarioHeader:
    """The shared header every preview page carries."""
    opportunity = scenario.opportunity
    return ScenarioHeader(
        key=scenario.key,
        title=scenario.title,
        summary=scenario.summary,
        notice=scenario.synthetic_notice,
        customer=opportunity.customer,
        sector=opportunity.sector,
        region=opportunity.region,
        scope=opportunity.scope,
        volume_band=opportunity.volume_band,
        timeline=tuple(
            TimelineRow(
                label=entry.label,
                date=entry.date,
                note=entry.note,
                is_critical=entry.is_critical,
            )
            for entry in opportunity.timeline
        ),
        choices=tuple(
            ScenarioChoice(key=key, title=title, is_active=key == scenario.key)
            for key, title in choices
        ),
    )


# --- customer intelligence ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCardView:
    """One system BidFusion would draw on, and what stands between."""

    name: str
    kind: str
    connection: StatusDisplay
    target_phase: str
    integration_options: tuple[str, ...]
    expected_data: tuple[str, ...]
    governance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    """One statement with its origin and how well it is backed."""

    text: str
    origin: str
    classification: StatusDisplay


@dataclass(frozen=True, slots=True)
class StakeholderRow:
    """One role on the customer side."""

    role: str
    interest: str
    influence: Meter
    engagement: Meter


@dataclass(frozen=True, slots=True)
class CustomerIntelligenceView:
    """Everything the customer intelligence page renders."""

    sources: tuple[SourceCardView, ...]
    insights: tuple[ClassifiedRow, ...]
    stakeholders: tuple[StakeholderRow, ...]
    relationship: Meter
    relationship_summary: str
    account_timeline: tuple[ClassifiedRow, ...]


def customer_intelligence_view(section: CustomerIntelligence) -> CustomerIntelligenceView:
    return CustomerIntelligenceView(
        sources=tuple(
            SourceCardView(
                name=source.name,
                kind=source.kind,
                connection=_chip(source.connection, _CONNECTION),
                target_phase=source.target_phase,
                integration_options=source.integration_options,
                expected_data=source.expected_data,
                governance=source.governance,
            )
            for source in section.sources
        ),
        insights=tuple(
            ClassifiedRow(
                text=insight.text,
                origin=insight.origin,
                classification=_chip(insight.classification, _EVIDENCE),
            )
            for insight in section.insights
        ),
        stakeholders=tuple(
            StakeholderRow(
                role=person.role,
                interest=person.interest,
                influence=_meter(person.influence, "Influence"),
                engagement=_meter(person.engagement, "Engagement"),
            )
            for person in section.stakeholders
        ),
        relationship=_meter(section.relationship_strength, "Relationship strength"),
        relationship_summary=section.relationship_summary,
        account_timeline=tuple(
            ClassifiedRow(
                text=signal.summary,
                origin=signal.period,
                classification=_chip(signal.classification, _EVIDENCE),
            )
            for signal in section.account_timeline
        ),
    )


# --- compliance ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComplianceRow:
    """One requirement and where it stands."""

    reference: str
    requirement: str
    state: StatusDisplay
    is_exclusion_criterion: bool
    evidence: str
    owner: str
    origin: str


@dataclass(frozen=True, slots=True)
class ComplianceView:
    """Everything the compliance page renders."""

    exclusion_criteria: tuple[ComplianceRow, ...]
    mandatory: tuple[ComplianceRow, ...]
    open_clarifications: tuple[str, ...]
    unresolved_count: int


_UNRESOLVED_COMPLIANCE = (
    ComplianceState.NOT_COMPLIANT,
    ComplianceState.PARTIALLY_COMPLIANT,
    ComplianceState.CLARIFICATION_REQUIRED,
    ComplianceState.EVIDENCE_REQUIRED,
    ComplianceState.UNKNOWN,
)


def compliance_view(section: Compliance) -> ComplianceView:
    rows = tuple(
        ComplianceRow(
            reference=item.reference,
            requirement=item.requirement,
            state=_chip(item.state, _COMPLIANCE),
            is_exclusion_criterion=item.is_exclusion_criterion,
            evidence=item.evidence,
            owner=item.owner,
            origin=item.origin,
        )
        for item in section.items
    )
    return ComplianceView(
        exclusion_criteria=tuple(row for row in rows if row.is_exclusion_criterion),
        mandatory=tuple(row for row in rows if not row.is_exclusion_criterion),
        open_clarifications=section.open_clarifications,
        unresolved_count=sum(1 for item in section.items if item.state in _UNRESOLVED_COMPLIANCE),
    )


# --- capability fit -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """How one requirement is covered, and by what."""

    requirement: str
    capability: str
    coverage: StatusDisplay
    evidence: str
    validity: str
    owner: str


@dataclass(frozen=True, slots=True)
class CapabilityFitView:
    """Everything the capability fit page renders."""

    items: tuple[CapabilityRow, ...]
    catalog_note: str
    confirmed_count: int
    gap_count: int
    unconfirmed_count: int
    legend: tuple[tuple[StatusDisplay, str], ...]


def capability_fit_view(section: CapabilityFit) -> CapabilityFitView:
    return CapabilityFitView(
        legend=tuple(
            (_chip(state, _COVERAGE), meaning) for state, meaning in _COVERAGE_MEANING.items()
        ),
        items=tuple(
            CapabilityRow(
                requirement=item.requirement,
                capability=item.capability,
                coverage=_chip(item.coverage, _COVERAGE),
                evidence=item.evidence,
                validity=item.validity,
                owner=item.owner,
            )
            for item in section.items
        ),
        catalog_note=section.catalog_note,
        confirmed_count=sum(
            1 for item in section.items if item.coverage is CoverageState.CONFIRMED
        ),
        gap_count=sum(1 for item in section.items if item.coverage is CoverageState.GAP),
        unconfirmed_count=sum(
            1
            for item in section.items
            if item.coverage
            in (CoverageState.EVIDENCE_REQUIRED, CoverageState.UNKNOWN, CoverageState.PARTIAL)
        ),
    )


# --- qualification ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorRow:
    """One qualification factor."""

    name: str
    verdict: StatusDisplay
    note: str
    owner: str
    is_must_pass: bool


@dataclass(frozen=True, slots=True)
class ConditionRow:
    """One condition attached to a positive assessment."""

    text: str
    owner: str
    due: str


@dataclass(frozen=True, slots=True)
class QualificationView:
    """Everything the qualification page renders."""

    system_assessment: StatusDisplay
    assessment_rationale: str
    decision_owner: str
    approval_state: str
    must_pass: tuple[FactorRow, ...]
    other_factors: tuple[FactorRow, ...]
    conditions: tuple[ConditionRow, ...]
    evidence_gaps: tuple[str, ...]


def qualification_view(section: Qualification) -> QualificationView:
    factors = tuple(
        FactorRow(
            name=factor.name,
            verdict=_chip(factor.verdict, _FACTOR),
            note=factor.note,
            owner=factor.owner,
            is_must_pass=factor.is_must_pass,
        )
        for factor in section.factors
    )
    return QualificationView(
        system_assessment=_chip(section.system_assessment, _ASSESSMENT),
        assessment_rationale=section.assessment_rationale,
        decision_owner=section.decision_owner,
        approval_state=section.approval_state,
        must_pass=tuple(factor for factor in factors if factor.is_must_pass),
        other_factors=tuple(factor for factor in factors if not factor.is_must_pass),
        conditions=tuple(
            ConditionRow(text=item.text, owner=item.owner, due=item.due)
            for item in section.conditions
        ),
        evidence_gaps=section.evidence_gaps,
    )


# --- competitive intelligence -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComparisonRowView:
    """One compared dimension, as two coarse bands and a takeaway."""

    dimension: str
    own: Meter
    competitor: Meter
    takeaway: str


@dataclass(frozen=True, slots=True)
class BattleCardView:
    """One battle card, with the approval it has not been given."""

    competitor_name: str
    our_position: str
    their_weakness: str
    proof_points: tuple[str, ...]
    approval_state: str


@dataclass(frozen=True, slots=True)
class CompetitorView:
    """One competitor and everything claimed about them."""

    key: str
    name: str
    positioning: str
    threat: StatusDisplay
    threat_meter: Meter
    signals: tuple[ClassifiedRow, ...]
    claims: tuple[str, ...]
    comparison: tuple[ComparisonRowView, ...]
    battle_card: BattleCardView | None


@dataclass(frozen=True, slots=True)
class CompetitiveIntelligenceView:
    """Everything the competitive intelligence page renders."""

    competitors: tuple[CompetitorView, ...]
    selected: CompetitorView
    intended_sources: tuple[str, ...]
    collection_note: str


def competitive_intelligence_view(
    section: CompetitiveIntelligence, competitor_key: str | None
) -> CompetitiveIntelligenceView:
    """Project the competitive picture, focused on one competitor.

    An unknown or missing key falls back to the first competitor rather
    than failing: the choice is a display preference, not an assertion
    about anything.
    """
    cards = {card.competitor_key: card for card in section.battle_cards}
    competitors = tuple(
        _competitor_view(competitor, cards.get(competitor.key), section)
        for competitor in section.competitors
    )
    selected = next(
        (item for item in competitors if item.key == competitor_key),
        competitors[0],
    )
    return CompetitiveIntelligenceView(
        competitors=competitors,
        selected=selected,
        intended_sources=section.intended_sources,
        collection_note=section.collection_note,
    )


def _competitor_view(
    competitor: Competitor,
    card: BattleCard | None,
    section: CompetitiveIntelligence,
) -> CompetitorView:
    names = {item.key: item.name for item in section.competitors}
    return CompetitorView(
        key=competitor.key,
        name=competitor.name,
        positioning=competitor.positioning,
        threat=_chip(competitor.threat_band, _THREAT),
        threat_meter=_meter(competitor.threat_level, "Assessed threat"),
        signals=tuple(
            ClassifiedRow(
                text=signal.text,
                origin=f"{signal.origin} · {signal.collected}",
                classification=_chip(signal.classification, _EVIDENCE),
            )
            for signal in competitor.signals
        ),
        claims=competitor.claims,
        comparison=tuple(
            ComparisonRowView(
                dimension=row.dimension,
                own=_meter(row.own_level, "Our position"),
                competitor=_meter(row.competitor_level, "Their position"),
                takeaway=row.takeaway,
            )
            for row in competitor.comparison
        ),
        battle_card=(
            BattleCardView(
                competitor_name=names.get(card.competitor_key, card.competitor_key),
                our_position=card.our_position,
                their_weakness=card.their_weakness,
                proof_points=card.proof_points,
                approval_state=card.approval_state,
            )
            if card is not None
            else None
        ),
    )


# --- win strategy -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HotButtonRow:
    """One thing the customer visibly cares about."""

    title: str
    detail: str
    origin: str
    classification: StatusDisplay


@dataclass(frozen=True, slots=True)
class ThemeRow:
    """One win theme, with its proof or the gap where proof is missing."""

    title: str
    statement: str
    classification: StatusDisplay
    proof_point: str | None
    evidence_gap: str | None


@dataclass(frozen=True, slots=True)
class WinStrategyView:
    """Everything the win strategy page renders."""

    hot_buttons: tuple[HotButtonRow, ...]
    themes: tuple[ThemeRow, ...]
    differentiators: tuple[str, ...]
    risks: tuple[str, ...]
    evaluator_takeaway: str
    approval_state: str
    unproven_theme_count: int


def win_strategy_view(section: WinStrategy) -> WinStrategyView:
    return WinStrategyView(
        hot_buttons=tuple(
            HotButtonRow(
                title=button.title,
                detail=button.detail,
                origin=button.origin,
                classification=_chip(button.classification, _EVIDENCE),
            )
            for button in section.hot_buttons
        ),
        themes=tuple(
            ThemeRow(
                title=theme.title,
                statement=theme.statement,
                classification=_chip(theme.classification, _EVIDENCE),
                proof_point=theme.proof_point,
                evidence_gap=theme.evidence_gap,
            )
            for theme in section.themes
        ),
        differentiators=section.differentiators,
        risks=section.risks,
        evaluator_takeaway=section.evaluator_takeaway,
        approval_state=section.approval_state,
        unproven_theme_count=sum(1 for theme in section.themes if theme.proof_point is None),
    )


# --- response lifecycle -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StageRow:
    """One stage of the intended response lifecycle."""

    key: str
    name: str
    purpose: str
    inputs: tuple[str, ...]
    human_step: str
    target_phase: str


@dataclass(frozen=True, slots=True)
class ResponseLifecycleView:
    """Everything the proposal factory page renders."""

    stages: tuple[StageRow, ...]
    grounding_rule: str
    export_note: str


def response_lifecycle_view(lifecycle: ResponseLifecycle) -> ResponseLifecycleView:
    return ResponseLifecycleView(
        stages=tuple(
            StageRow(
                key=stage.key,
                name=stage.name,
                purpose=stage.purpose,
                inputs=stage.inputs,
                human_step=stage.human_step,
                target_phase=stage.target_phase,
            )
            for stage in lifecycle.stages
        ),
        grounding_rule=lifecycle.grounding_rule,
        export_note=lifecycle.export_note,
    )


# --- review and approval ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewRow:
    """One extracted item a human would decide on."""

    reference: str
    kind: str
    proposed: str
    origin: str
    state: StatusDisplay
    reviewer_role: str


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """One decision, as the history would record it."""

    reference: str
    outcome: str
    reviewer_role: str
    note: str


@dataclass(frozen=True, slots=True)
class ReviewApprovalView:
    """Everything the review and approval page renders."""

    items: tuple[ReviewRow, ...]
    history: tuple[DecisionRow, ...]
    submission_readiness: str
    blocking_items: tuple[str, ...]
    awaiting_count: int


def review_approval_view(section: ReviewApproval) -> ReviewApprovalView:
    return ReviewApprovalView(
        items=tuple(
            ReviewRow(
                reference=item.reference,
                kind=item.kind,
                proposed=item.proposed,
                origin=item.origin,
                state=_chip(item.state, _REVIEW),
                reviewer_role=item.reviewer_role,
            )
            for item in section.items
        ),
        history=tuple(
            DecisionRow(
                reference=decision.reference,
                outcome=decision.outcome,
                reviewer_role=decision.reviewer_role,
                note=decision.note,
            )
            for decision in section.history
        ),
        submission_readiness=section.submission_readiness,
        blocking_items=section.blocking_items,
        awaiting_count=sum(
            1 for item in section.items if item.state is ReviewState.AWAITING_REVIEW
        ),
    )
