"""Contracts for the curated demonstration scenarios.

The preview pages show what BidFusion is meant to do before the systems
behind it exist. That is only safe if the demonstration data is as
strictly shaped as real data would be: every scenario file is validated
against these models before a single value reaches a template, so a
malformed, over-claiming, or half-written fixture fails loudly at load
time instead of rendering as if it were a result.

Schema-first, like the rest of the codebase (ADR-0005): strict models,
``extra="forbid"``, frozen. Nothing here reads a file, and nothing here
knows about Flask.

Everything these models describe is invented. Customers, competitors,
signals, and figures in the fixture files name no real organization and
no real person — see fixtures/product_demo/README.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

#: Coarse 1-5 band. Deliberately not a percentage: a demonstration must
#: not imply a precision that no measurement stands behind, and the
#: interface renders these as fixed CSS steps rather than inline widths.
Level = Annotated[int, Field(ge=1, le=5)]

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=600)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9-]{3,60}$")]


class StrictModel(BaseModel):
    """Frozen, strict base for every preview contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ConnectionState(StrEnum):
    """Whether a named source is actually wired up."""

    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED = "CONNECTED"


class EvidenceClass(StrEnum):
    """How well one statement is backed. Never hidden from the reader."""

    EVIDENCE_BACKED = "EVIDENCE_BACKED"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    DEMO = "DEMO"


class ComplianceState(StrEnum):
    """Compliance state of one requirement. Unknown is a first-class value."""

    COMPLIANT = "COMPLIANT"
    PARTIALLY_COMPLIANT = "PARTIALLY_COMPLIANT"
    NOT_COMPLIANT = "NOT_COMPLIANT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    UNKNOWN = "UNKNOWN"


class CoverageState(StrEnum):
    """How well a capability covers a requirement."""

    CONFIRMED = "CONFIRMED"
    PARTIAL = "PARTIAL"
    GAP = "GAP"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    UNKNOWN = "UNKNOWN"


class AssessmentVerdict(StrEnum):
    """The system's reading of a qualification. Never the decision itself."""

    GO = "GO"
    GO_WITH_CONDITIONS = "GO_WITH_CONDITIONS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_GO = "NO_GO"


class FactorVerdict(StrEnum):
    """One qualification factor's reading."""

    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class ThreatBand(StrEnum):
    """How much of a threat a competitor is taken to be."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewState(StrEnum):
    """Where one item stands in human review."""

    AWAITING_REVIEW = "AWAITING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"


class TimelineEntry(StrictModel):
    """One dated milestone of the opportunity."""

    label: ShortText
    date: ShortText
    note: ShortText
    is_critical: bool = False


class Opportunity(StrictModel):
    """The invented opportunity a scenario is built around."""

    customer: ShortText
    sector: ShortText
    region: ShortText
    scope: LongText
    volume_band: ShortText
    timeline: tuple[TimelineEntry, ...] = Field(min_length=1, max_length=10)


class SourceCard(StrictModel):
    """One system BidFusion would draw on, and what stands between."""

    key: Slug
    name: ShortText
    kind: ShortText
    connection: ConnectionState
    target_phase: ShortText
    integration_options: tuple[ShortText, ...] = Field(max_length=4)
    expected_data: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    governance: tuple[ShortText, ...] = Field(min_length=1, max_length=4)


class Insight(StrictModel):
    """One statement with where it came from and how well it is backed."""

    text: LongText
    origin: ShortText
    classification: EvidenceClass


class Stakeholder(StrictModel):
    """One role on the customer side. Roles only — never a named person."""

    role: ShortText
    interest: ShortText
    influence: Level
    engagement: Level


class RelationshipSignal(StrictModel):
    """One recorded touchpoint in the account history."""

    period: ShortText
    summary: LongText
    classification: EvidenceClass


class CustomerIntelligence(StrictModel):
    """Everything the customer intelligence page demonstrates."""

    sources: tuple[SourceCard, ...] = Field(min_length=1, max_length=8)
    insights: tuple[Insight, ...] = Field(min_length=1, max_length=8)
    stakeholders: tuple[Stakeholder, ...] = Field(min_length=1, max_length=8)
    relationship_strength: Level
    relationship_summary: LongText
    account_timeline: tuple[RelationshipSignal, ...] = Field(min_length=1, max_length=8)


class ComplianceItem(StrictModel):
    """One requirement and where it stands."""

    reference: ShortText
    requirement: LongText
    state: ComplianceState
    is_exclusion_criterion: bool
    evidence: ShortText
    owner: ShortText
    origin: ShortText


class Compliance(StrictModel):
    """Everything the compliance page demonstrates."""

    items: tuple[ComplianceItem, ...] = Field(min_length=1, max_length=14)
    open_clarifications: tuple[ShortText, ...] = Field(max_length=6)


class CapabilityItem(StrictModel):
    """How one requirement is covered, and by what."""

    requirement: LongText
    capability: ShortText
    coverage: CoverageState
    evidence: ShortText
    validity: ShortText
    owner: ShortText


class CapabilityFit(StrictModel):
    """Everything the capability fit page demonstrates."""

    items: tuple[CapabilityItem, ...] = Field(min_length=1, max_length=12)
    catalog_note: LongText


class QualificationFactor(StrictModel):
    """One factor of the qualification assessment."""

    name: ShortText
    verdict: FactorVerdict
    note: LongText
    owner: ShortText
    is_must_pass: bool = False


class QualificationCondition(StrictModel):
    """One condition that must close before a go can hold."""

    text: LongText
    owner: ShortText
    due: ShortText


class Qualification(StrictModel):
    """Everything the qualification page demonstrates."""

    system_assessment: AssessmentVerdict
    assessment_rationale: LongText
    decision_owner: ShortText
    approval_state: ShortText
    factors: tuple[QualificationFactor, ...] = Field(min_length=1, max_length=10)
    conditions: tuple[QualificationCondition, ...] = Field(max_length=6)
    evidence_gaps: tuple[ShortText, ...] = Field(max_length=6)


class CompetitorSignal(StrictModel):
    """One observation about a competitor, with when it was collected."""

    text: LongText
    collected: ShortText
    origin: ShortText
    classification: EvidenceClass


class ComparisonRow(StrictModel):
    """One dimension compared, as coarse bands rather than false precision."""

    dimension: ShortText
    own_level: Level
    competitor_level: Level
    takeaway: ShortText


class Competitor(StrictModel):
    """One invented competitor and what is claimed about them."""

    key: Slug
    name: ShortText
    positioning: LongText
    threat_band: ThreatBand
    threat_level: Level
    signals: tuple[CompetitorSignal, ...] = Field(min_length=1, max_length=6)
    claims: tuple[ShortText, ...] = Field(max_length=4)
    comparison: tuple[ComparisonRow, ...] = Field(min_length=1, max_length=6)


class BattleCard(StrictModel):
    """The battle card a reviewer would approve before anyone uses it."""

    competitor_key: Slug
    our_position: LongText
    their_weakness: LongText
    proof_points: tuple[ShortText, ...] = Field(min_length=1, max_length=4)
    approval_state: ShortText


class CompetitiveIntelligence(StrictModel):
    """Everything the competitive intelligence page demonstrates."""

    competitors: tuple[Competitor, ...] = Field(min_length=1, max_length=6)
    battle_cards: tuple[BattleCard, ...] = Field(max_length=6)
    intended_sources: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    collection_note: LongText


class HotButton(StrictModel):
    """One thing the customer visibly cares about."""

    title: ShortText
    detail: LongText
    origin: ShortText
    classification: EvidenceClass


class WinTheme(StrictModel):
    """One theme, with the proof behind it or the gap where proof is missing."""

    title: ShortText
    statement: LongText
    classification: EvidenceClass
    proof_point: ShortText | None = None
    evidence_gap: ShortText | None = None


class WinStrategy(StrictModel):
    """Everything the win strategy page demonstrates."""

    hot_buttons: tuple[HotButton, ...] = Field(min_length=1, max_length=6)
    themes: tuple[WinTheme, ...] = Field(min_length=1, max_length=6)
    differentiators: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    risks: tuple[ShortText, ...] = Field(min_length=1, max_length=6)
    evaluator_takeaway: LongText
    approval_state: ShortText


class ProposalStage(StrictModel):
    """One stage of the intended response lifecycle."""

    key: Slug
    name: ShortText
    purpose: LongText
    inputs: tuple[ShortText, ...] = Field(min_length=1, max_length=4)
    human_step: LongText
    target_phase: ShortText


class ResponseLifecycle(StrictModel):
    """The intended path from a reviewed package to a submitted response.

    Product structure rather than scenario content: the stages are the
    same whichever opportunity is being looked at, so they are held once
    instead of repeated in every scenario.
    """

    schema_version: ShortText
    stages: tuple[ProposalStage, ...] = Field(min_length=1, max_length=8)
    grounding_rule: LongText
    export_note: LongText


class ReviewItem(StrictModel):
    """One extracted item a human would decide on."""

    reference: ShortText
    kind: ShortText
    proposed: LongText
    origin: ShortText
    state: ReviewState
    reviewer_role: ShortText


class ReviewDecision(StrictModel):
    """One past decision, as the decision history would record it."""

    reference: ShortText
    outcome: ShortText
    reviewer_role: ShortText
    note: ShortText


class ReviewApproval(StrictModel):
    """Everything the review and approval page demonstrates."""

    items: tuple[ReviewItem, ...] = Field(min_length=1, max_length=10)
    history: tuple[ReviewDecision, ...] = Field(max_length=8)
    submission_readiness: LongText
    blocking_items: tuple[ShortText, ...] = Field(max_length=6)


class Scenario(StrictModel):
    """One complete, self-contained demonstration scenario."""

    schema_version: ShortText
    key: Slug
    title: ShortText
    summary: LongText
    synthetic_notice: LongText
    opportunity: Opportunity
    customer_intelligence: CustomerIntelligence
    compliance: Compliance
    capability_fit: CapabilityFit
    qualification: Qualification
    competitive_intelligence: CompetitiveIntelligence
    win_strategy: WinStrategy
    review_approval: ReviewApproval


#: The schema version every scenario file must declare. Bumping this is
#: a deliberate act: it invalidates every fixture that has not been
#: migrated, which is exactly what should happen.
SCENARIO_SCHEMA_VERSION = "1.0.0"
