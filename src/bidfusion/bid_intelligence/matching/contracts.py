"""Bridge contracts between extracted RFP requirements and golden matching.

This is the bid-side half of the RFP-to-Golden-Knowledge slice. It
deliberately reuses both existing vocabularies instead of inventing a
third one:

- the RFP side keeps its own provenance (:class:`SourceReference`,
  :class:`RequirementModality`) exactly as extraction recorded it;
- the golden side keeps its own statuses and provenance
  (:class:`MatchStatus`, :class:`EvidenceReference`, the pilot
  capability and technology taxonomies).

The two provenances are carried side by side and are never collapsed
into one string. Nothing here writes to the golden store, and no golden
contract gains a bid identifier — the dependency points strictly from
the bid domain into the golden domain.

Trust semantics: an assessment is a *candidate* result. ``MATCHED``
means a candidate golden claim matches the normalized requirement — it
never means the requirement is fulfilled. ``GAP`` means no supporting
claim exists in the current golden snapshot — it never means the
company lacks the capability. Every assessment is born
``HumanReviewStatus.REQUIRED`` and cannot be constructed otherwise.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    ClaimId,
    ClaimStatus,
    EvidenceReference,
    HumanReviewStatus,
    MatchStatus,
    Technology,
)
from bidfusion.schemas.common import BidfusionModel, RequirementModality, SemanticVersion
from bidfusion.schemas.ids import BidId, RequirementId
from bidfusion.schemas.provenance import SourceReference

ASSESSMENT_VERSION = "1.0.0"


class KnowledgeStoreState(StrEnum):
    """Availability of the golden knowledge snapshot for one assessment run.

    These states are batch-level facts about the knowledge side and are
    deliberately distinct from per-requirement match statuses: an absent
    or damaged store is *not* a capability gap and must never be shown
    as one.
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_CLAIMS = "NO_CLAIMS"
    UNREADABLE = "UNREADABLE"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"


class RequirementLanguage(StrEnum):
    """Deterministic reading of the requirement's obligation language."""

    OBLIGATION = "OBLIGATION"
    NEGATED_OR_EXCLUDED = "NEGATED_OR_EXCLUDED"


class RequirementKnowledgeAssessment(BidfusionModel):
    """One RFP requirement connected to the golden knowledge pilot.

    ``match_status`` is ``None`` exactly when no deterministic verdict
    was produced — the knowledge store was unavailable, unreadable, or
    empty. That absence is reported through the batch store state and
    must never be mapped onto ``GAP``.
    """

    assessment_id: str = Field(pattern=r"^RKA-[0-9a-f]{12}$")
    assessment_version: SemanticVersion = ASSESSMENT_VERSION
    bid_id: BidId
    requirement_id: RequirementId
    requirement_text: str = Field(min_length=1)
    requirement_modality: RequirementModality
    requirement_source: SourceReference
    additional_requirement_sources: tuple[SourceReference, ...] = Field(default_factory=tuple)
    requirement_language: RequirementLanguage
    technology_hint: Technology
    capability_hints: tuple[CapabilityCategory, ...] = Field(default_factory=tuple)
    match_status: MatchStatus | None = None
    matched_claim_id: ClaimId | None = None
    matched_capability: CapabilityCategory | None = None
    knowledge_claim_status: ClaimStatus | None = None
    evidence_refs: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    rationale: str = Field(min_length=1)
    human_review_status: HumanReviewStatus = HumanReviewStatus.REQUIRED

    @model_validator(mode="after")
    def _assessment_is_a_candidate_only(self) -> RequirementKnowledgeAssessment:
        if self.human_review_status is not HumanReviewStatus.REQUIRED:
            msg = "a bridge assessment is always born requiring human review"
            raise ValueError(msg)
        if self.match_status in (MatchStatus.MATCHED, MatchStatus.PARTIAL):
            if self.matched_claim_id is None:
                msg = "a matched or partial assessment must reference a claim"
                raise ValueError(msg)
            if not self.evidence_refs:
                msg = "a matched or partial assessment must carry evidence"
                raise ValueError(msg)
        else:
            if self.matched_claim_id is not None:
                msg = "only matched or partial assessments may reference a claim"
                raise ValueError(msg)
        if self.requirement_source.bid_id != self.bid_id:
            msg = "assessment requirement source must belong to the assessment bid"
            raise ValueError(msg)
        for source in self.additional_requirement_sources:
            if source.bid_id != self.bid_id:
                msg = "additional requirement sources must belong to the assessment bid"
                raise ValueError(msg)
        return self

    @property
    def mandatory(self) -> bool:
        """Whether the underlying requirement expresses a MUST obligation."""
        return self.requirement_modality is RequirementModality.MUST


class KnowledgeAssessmentResult(BidfusionModel):
    """One deterministic assessment batch plus the knowledge-side state.

    ``store_note`` is a static, operator-safe sentence chosen from a
    fixed table by store state; it never carries store content, raw
    exception text, or a filesystem path.
    """

    assessment_version: SemanticVersion = ASSESSMENT_VERSION
    store_state: KnowledgeStoreState
    store_note: str = Field(min_length=1)
    claim_count: int = Field(ge=0)
    assessments: tuple[RequirementKnowledgeAssessment, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _result_is_coherent(self) -> KnowledgeAssessmentResult:
        if self.store_state is not KnowledgeStoreState.AVAILABLE:
            if any(item.match_status is not None for item in self.assessments):
                msg = "no match verdict may exist without an available knowledge store"
                raise ValueError(msg)
            if self.claim_count != 0:
                msg = "an unavailable knowledge store cannot report claims"
                raise ValueError(msg)
        ids = [item.assessment_id for item in self.assessments]
        if len(ids) != len(set(ids)):
            msg = "assessment IDs must be unique within one result"
            raise ValueError(msg)
        return self
