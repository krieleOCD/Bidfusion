"""Reviewed Working Package contract: the persisted Level-1 loop output.

A Reviewed Working Package is the formal, versioned artifact produced
when a completed bid run's requirement assessments are combined with
the human reviews recorded against them. It is a *snapshot*: generating
it never mutates the run, the assessments, the reviews, or any golden
knowledge state.

The three trust layers stay separate on every requirement entry:

1. **Machine assessment** — the deterministic candidate match
   (``match_status``), which never means the requirement is fulfilled.
2. **Golden knowledge state** — the matched claim's own trust status
   (``claim_status``) and its evidence references (metadata only, never
   raw golden section text).
3. **Human bid review** — the recorded decision for this bid run
   (``human_review``), which never validates or promotes a golden claim.

No field of this contract may collapse those layers into one combined
"compliant"/"fulfilled" verdict; the package-level state only reports
review *coverage* (``REVIEW_COMPLETE`` / ``REVIEW_INCOMPLETE``).

Integrity follows the project's sealing convention
(:mod:`bidfusion.shared.payloads`): the package embeds an
:class:`ArtifactEnvelope` whose ``content_hash`` binds every content
field, and the store re-verifies that seal on every load.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Annotated

from pydantic import Field, model_validator

from bidfusion.bid_intelligence.matching.contracts import RequirementLanguage
from bidfusion.bid_intelligence.review.contracts import (
    MAX_RATIONALE_LENGTH,
    MAX_REVIEWER_LENGTH,
    ReviewDecision,
    ReviewId,
    ReviewState,
)
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    ClaimId,
    ClaimStatus,
    EvidenceReference,
    MatchStatus,
    Technology,
)
from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.common import (
    BidfusionModel,
    RequirementModality,
    SemanticVersion,
    Sha256Digest,
)
from bidfusion.schemas.ids import BidId, RequirementId, RunId
from bidfusion.schemas.provenance import SourceReference

REVIEWED_PACKAGE_SCHEMA_VERSION = "1.0.0"
REVIEWED_PACKAGE_DOMAIN = "reviewed_working_package"

#: Package identifiers are content-derived like every other BidFusion
#: identifier family; they share no format with golden or review IDs.
ReviewedPackageId = Annotated[str, Field(pattern=r"^RWP-[0-9a-f]{12}$")]


class PackageReviewState(StrEnum):
    """Review *coverage* of one package — never a compliance verdict.

    ``REVIEW_COMPLETE`` means every requirement entry carries an
    applicable human review. ``REVIEW_INCOMPLETE`` means at least one is
    still pending. Neither says anything about whether the bid can meet
    the requirements.
    """

    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"


def package_id_for(run_id: str, package_version: int) -> str:
    """Deterministic package identifier for one run's package version."""
    digest = sha256(f"{run_id}|{package_version}".encode()).hexdigest()
    return f"RWP-{digest[:12]}"


class PackageRfpRequirement(BidfusionModel):
    """The original RFP requirement exactly as extraction recorded it."""

    requirement_id: RequirementId
    text: str = Field(min_length=1)
    modality: RequirementModality
    source: SourceReference
    additional_sources: tuple[SourceReference, ...] = Field(default_factory=tuple)


class PackageMachineAssessment(BidfusionModel):
    """The deterministic candidate assessment — a candidate, not a verdict.

    ``match_status`` is ``None`` exactly when the knowledge store
    produced no verdict for this run; that absence is never mapped onto
    a gap. The digest binds this entry to the exact assessment content
    the package snapshot was built from.
    """

    assessment_id: str = Field(pattern=r"^RKA-[0-9a-f]{12}$")
    assessment_version: SemanticVersion
    assessment_digest: Sha256Digest
    requirement_language: RequirementLanguage
    technology_hint: Technology
    capability_hints: tuple[CapabilityCategory, ...] = Field(default_factory=tuple)
    match_status: MatchStatus | None = None
    matched_claim_id: ClaimId | None = None
    matched_capability: CapabilityCategory | None = None
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _candidate_shape_is_coherent(self) -> PackageMachineAssessment:
        if self.match_status in (MatchStatus.MATCHED, MatchStatus.PARTIAL):
            if self.matched_claim_id is None:
                msg = "a matched or partial package entry must reference a claim"
                raise ValueError(msg)
        elif self.matched_claim_id is not None:
            msg = "only matched or partial package entries may reference a claim"
            raise ValueError(msg)
        return self


class PackageGoldenKnowledge(BidfusionModel):
    """The golden side of one entry: claim trust state plus evidence refs.

    Evidence references are provenance metadata only (source, section,
    locator, version) — raw golden section text is never duplicated into
    a package. ``claim_status`` is the golden claim's *own* trust state;
    a bid-side review never changes it.
    """

    claim_status: ClaimStatus | None = None
    evidence_refs: tuple[EvidenceReference, ...] = Field(default_factory=tuple)


class PackageHumanReview(BidfusionModel):
    """One recorded human decision, copied verbatim from the review record."""

    review_id: ReviewId
    review_version: int = Field(ge=1)
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=MAX_REVIEWER_LENGTH)
    reviewed_at: datetime
    rationale: str | None = Field(default=None, min_length=1, max_length=MAX_RATIONALE_LENGTH)

    @model_validator(mode="after")
    def _review_timestamp_is_aware(self) -> PackageHumanReview:
        if self.reviewed_at.tzinfo is None:
            msg = "a package review timestamp must be timezone-aware"
            raise ValueError(msg)
        return self


class ReviewedPackageRequirement(BidfusionModel):
    """One requirement with its three trust layers, preserved separately."""

    rfp: PackageRfpRequirement
    machine: PackageMachineAssessment
    golden: PackageGoldenKnowledge
    human_review: PackageHumanReview | None = None

    @model_validator(mode="after")
    def _matched_entries_carry_evidence(self) -> ReviewedPackageRequirement:
        if (
            self.machine.match_status in (MatchStatus.MATCHED, MatchStatus.PARTIAL)
            and not self.golden.evidence_refs
        ):
            msg = "a matched or partial package entry must carry evidence references"
            raise ValueError(msg)
        return self

    @property
    def review_state(self) -> ReviewState:
        """The human-review dimension of this entry; PENDING = no review."""
        if self.human_review is None:
            return ReviewState.PENDING
        return ReviewState(self.human_review.decision.value)


class PackageReviewSummary(BidfusionModel):
    """Deterministic review-coverage counts over the package entries."""

    total_requirements: int = Field(ge=0)
    reviewed: int = Field(ge=0)
    pending: int = Field(ge=0)
    confirmed_candidate: int = Field(ge=0)
    rejected_candidate: int = Field(ge=0)
    needs_clarification: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> PackageReviewSummary:
        if self.reviewed + self.pending != self.total_requirements:
            msg = "reviewed and pending counts must sum to the total"
            raise ValueError(msg)
        if (
            self.confirmed_candidate + self.rejected_candidate + self.needs_clarification
            != self.reviewed
        ):
            msg = "review decision counts must sum to the reviewed count"
            raise ValueError(msg)
        return self


def summarize_entries(
    entries: tuple[ReviewedPackageRequirement, ...],
) -> PackageReviewSummary:
    """The canonical summary of one entry tuple; used to build and to verify."""
    states = [entry.review_state for entry in entries]
    return PackageReviewSummary(
        total_requirements=len(entries),
        reviewed=sum(1 for state in states if state is not ReviewState.PENDING),
        pending=sum(1 for state in states if state is ReviewState.PENDING),
        confirmed_candidate=sum(1 for state in states if state is ReviewState.CONFIRMED),
        rejected_candidate=sum(1 for state in states if state is ReviewState.REJECTED),
        needs_clarification=sum(1 for state in states if state is ReviewState.NEEDS_CLARIFICATION),
    )


class ReviewedWorkingPackage(BidfusionModel):
    """One immutable, versioned snapshot of the reviewed run state.

    ``source_requirements`` references the run's sealed requirement
    extraction artifact — the RFP provenance root this package was built
    from. ``created_at`` is the only explicitly versioned creation
    metadata; every other field is a pure function of the authoritative
    inputs.
    """

    artifact: ArtifactEnvelope
    package_id: ReviewedPackageId
    package_version: int = Field(ge=1)
    bid_id: BidId
    run_id: RunId
    created_at: datetime
    assessment_version: SemanticVersion
    source_requirements: ArtifactReference
    requirements: tuple[ReviewedPackageRequirement, ...] = Field(default_factory=tuple)
    summary: PackageReviewSummary
    package_review_state: PackageReviewState

    @model_validator(mode="after")
    def _package_is_canonical(self) -> ReviewedWorkingPackage:
        if self.artifact.artifact_type is not ArtifactType.REVIEWED_WORKING_PACKAGE:
            msg = "reviewed working packages require a reviewed_working_package artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.artifact.run_id != self.run_id:
            msg = "the package artifact must belong to the package bid and run"
            raise ValueError(msg)
        if self.package_id != package_id_for(self.run_id, self.package_version):
            msg = "package_id must be derived from the run and package version"
            raise ValueError(msg)
        if self.created_at.tzinfo is None:
            msg = "the package creation timestamp must be timezone-aware"
            raise ValueError(msg)
        if self.source_requirements.artifact_type is not ArtifactType.EXTRACTION_RESULT:
            msg = "the package source must be the run's requirement extraction artifact"
            raise ValueError(msg)
        if (
            self.source_requirements.bid_id != self.bid_id
            or self.source_requirements.run_id != self.run_id
        ):
            msg = "the package source artifact must belong to the package bid and run"
            raise ValueError(msg)
        input_ids = {item.artifact_id for item in self.artifact.input_artifacts}
        if self.source_requirements.artifact_id not in input_ids:
            msg = "the package lineage must include its requirement extraction artifact"
            raise ValueError(msg)
        requirement_ids = [entry.rfp.requirement_id for entry in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            msg = "package requirement entries must be unique per requirement"
            raise ValueError(msg)
        assessment_ids = [entry.machine.assessment_id for entry in self.requirements]
        if len(assessment_ids) != len(set(assessment_ids)):
            msg = "package requirement entries must be unique per assessment"
            raise ValueError(msg)
        for entry in self.requirements:
            if entry.machine.assessment_version != self.assessment_version:
                msg = "every package entry must share the package assessment version"
                raise ValueError(msg)
            for source in (entry.rfp.source, *entry.rfp.additional_sources):
                if source.bid_id != self.bid_id:
                    msg = "package requirement sources must belong to the package bid"
                    raise ValueError(msg)
        if self.summary != summarize_entries(self.requirements):
            msg = "the package summary must equal the recount of its entries"
            raise ValueError(msg)
        expected_state = (
            PackageReviewState.REVIEW_COMPLETE
            if self.summary.pending == 0
            else PackageReviewState.REVIEW_INCOMPLETE
        )
        if self.package_review_state is not expected_state:
            msg = "the package review state must follow from its pending count"
            raise ValueError(msg)
        return self
