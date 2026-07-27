"""Adversarial tests for Foundation 1.1 architectural invariants."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from bidfusion.schemas import (
    ActorId,
    Approval,
    ApprovalDecision,
    ArtifactEnvelope,
    ArtifactId,
    ArtifactProducer,
    ArtifactReference,
    ArtifactType,
    Bid,
    BidBusinessState,
    BidDecision,
    BidDecisionStatus,
    BidId,
    BusinessReview,
    BusinessReviewStatus,
    BusinessReviewType,
    CanonicalDocument,
    CapabilityId,
    CapabilityMatch,
    ComplianceItem,
    ComplianceMatrix,
    ComplianceStatus,
    CoverageResult,
    DataClassification,
    DocumentId,
    DocumentMetadata,
    EvidencedStatement,
    EvidenceReference,
    ExecutiveOverview,
    ExtractionCompleteness,
    ExtractionInfo,
    ExtractionStream,
    HumanReview,
    KnowledgeApprovalStatus,
    KnowledgeEvidence,
    KnowledgeGovernance,
    KnowledgeItemId,
    KnowledgeSource,
    KnowledgeSourceType,
    MatchStatus,
    ModelRequirements,
    NormalizedBidDataset,
    NormalizedObjectReference,
    NormalizedObjectType,
    Opportunity,
    OpportunityId,
    Page,
    Paragraph,
    ProcessingRun,
    ProcessingStage,
    ProcessingStatus,
    Requirement,
    RequirementCategory,
    RequirementId,
    RequirementModality,
    ReviewDecision,
    ReviewId,
    RunId,
    SecurityClearedArtifact,
    SecurityManualReview,
    SecurityResult,
    SecurityReviewDisposition,
    SecurityVerdict,
    SourceLocator,
    SourceReference,
    WorkingPackage,
)

BID_ID = "BID-2026-000123"
OTHER_BID_ID = "BID-2026-000999"
RUN_ID = "RUN-20260727-0001"
RAW_ARTIFACT_ID = "ART-20260727-000001"
CANONICAL_ARTIFACT_ID = "ART-20260727-000002"
EXTRACTION_ARTIFACT_ID = "ART-20260727-000003"
NORMALIZED_ARTIFACT_ID = "ART-20260727-000004"
HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)


def artifact_reference(
    *,
    artifact_id: str = RAW_ARTIFACT_ID,
    bid_id: str = BID_ID,
    artifact_type: ArtifactType | str = ArtifactType.RAW_DOCUMENT,
    content_hash: str = HASH_A,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=RUN_ID,
        artifact_type=ArtifactType(artifact_type),
        schema_version="1.0.0",
        content_ref=f"artifacts/{artifact_id}",
        content_hash=content_hash,
    )


def artifact_envelope(
    *,
    artifact_id: str,
    artifact_type: ArtifactType | str,
    inputs: list[ArtifactReference],
    bid_id: str = BID_ID,
) -> ArtifactEnvelope:
    return ArtifactEnvelope.model_validate(
        {
            "artifact_id": artifact_id,
            "bid_id": bid_id,
            "run_id": RUN_ID,
            "artifact_type": ArtifactType(artifact_type),
            "schema_version": "1.0.0",
            "producer": ArtifactProducer(component="test-producer", version="1.2.3"),
            "input_artifacts": inputs,
            "created_at": NOW,
            "content_ref": f"artifacts/{artifact_id}",
            "content_hash": HASH_B,
        }
    )


def source_reference(
    *,
    canonical_artifact_id: str = CANONICAL_ARTIFACT_ID,
    bid_id: str = BID_ID,
) -> SourceReference:
    return SourceReference(
        bid_id=bid_id,
        document_id="DOC-003",
        filename="requirements.pdf",
        document_hash=HASH_A,
        canonical_artifact_id=canonical_artifact_id,
        locator=SourceLocator(
            page=34,
            section_id="SEC-5.2",
            paragraph_id="PAR-0042",
        ),
        quote="24/7 incident response must be provided",
    )


def security_result(
    verdict: SecurityVerdict,
    *,
    artifact: ArtifactReference | None = None,
    manual_review: SecurityManualReview | None = None,
) -> SecurityResult:
    raw_artifact = artifact or artifact_reference()
    return SecurityResult(
        bid_id=BID_ID,
        document_id="DOC-003",
        artifact=raw_artifact,
        content_hash=raw_artifact.content_hash,
        verdict=verdict,
        scanner="foundation-test-scanner",
        scanner_version="1.0.0",
        policy_version="2026.07",
        decided_at=NOW,
        manual_review=manual_review,
    )


def approved_evidence(
    *,
    bid_capability_id: str = "CAP-018",
    status: KnowledgeApprovalStatus = KnowledgeApprovalStatus.APPROVED,
    valid_until: datetime | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        knowledge_item_id="KNW-000018",
        capability_id=bid_capability_id,
        knowledge_version=3,
        approval_status=status,
        valid_from=NOW - timedelta(days=30),
        valid_until=valid_until,
        checked_at=NOW,
        evidence_ids=("EVD-001",),
    )


def capability_match(
    *,
    bid_id: str = BID_ID,
    evidence: list[EvidenceReference] | None = None,
) -> CapabilityMatch:
    return CapabilityMatch(
        bid_id=bid_id,
        requirement_id="REQ-000042",
        status=MatchStatus.SUPPORTED,
        capability_id="CAP-018",
        confidence=0.91,
        evaluated_at=NOW,
        evidence=(approved_evidence(),) if evidence is None else tuple(evidence),
    )


def requirement() -> Requirement:
    return Requirement(
        requirement_id="REQ-000042",
        bid_id=BID_ID,
        original_text="24/7 incident response must be provided",
        modality=RequirementModality.MUST,
        category=RequirementCategory.SECURITY,
        confidence=0.97,
        source=source_reference(),
        extraction=ExtractionInfo(
            method="llm",
            producer="requirement-extractor",
            producer_version="1.0.0",
            model="gateway-route-7",
            prompt_version="v1",
        ),
    )


@pytest.mark.parametrize(
    ("id_type", "bad_value"),
    [
        (BidId, "bid-2026-000123"),
        (OpportunityId, "OPP-12"),
        (DocumentId, "DOC-X"),
        (RequirementId, "REQ-42"),
        (CapabilityId, "CAP-X"),
        (RunId, "RUN-today-1"),
        (ArtifactId, "ART-1"),
        (ReviewId, "REVIEW-1"),
        (ActorId, "ACT-X"),
        (KnowledgeItemId, "KNW-1"),
    ],
)
def test_malformed_typed_ids_fail(id_type: Any, bad_value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(id_type).validate_python(bad_value)


def test_strict_contract_rejects_unknown_fields() -> None:
    data = artifact_reference().model_dump()
    data["undeclared"] = "must fail"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ArtifactReference.model_validate(data)


def test_artifact_envelope_carries_versioned_lineage() -> None:
    raw = artifact_reference()
    canonical = artifact_envelope(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type="canonical_document",
        inputs=[raw],
    )
    assert canonical.run_id == RUN_ID
    assert canonical.schema_version == "1.0.0"
    assert canonical.producer.version == "1.2.3"
    assert canonical.input_artifacts[0].content_hash == HASH_A


def test_artifact_lineage_rejects_cross_bid_input() -> None:
    with pytest.raises(ValidationError, match="envelope bid"):
        artifact_envelope(
            artifact_id=CANONICAL_ARTIFACT_ID,
            artifact_type="canonical_document",
            inputs=[artifact_reference(bid_id=OTHER_BID_ID)],
        )


@pytest.mark.parametrize("verdict", [SecurityVerdict.BLOCK, SecurityVerdict.QUARANTINE])
def test_block_and_quarantine_cannot_proceed(verdict: SecurityVerdict) -> None:
    result = security_result(verdict)
    assert not result.allows_processing
    with pytest.raises(ValidationError, match="does not permit processing"):
        SecurityClearedArtifact(
            artifact=result.artifact,
            document_id=result.document_id,
            security_result=result,
        )


def test_manual_review_is_pending_before_explicit_release() -> None:
    result = security_result(SecurityVerdict.MANUAL_REVIEW)
    assert result.manual_review is None
    assert not result.allows_processing
    with pytest.raises(ValidationError, match="does not permit processing"):
        SecurityClearedArtifact(
            artifact=result.artifact,
            document_id=result.document_id,
            security_result=result,
        )


def test_manual_review_release_is_audited_and_permits_handoff() -> None:
    audit = SecurityManualReview(
        review_id="REV-000042",
        reviewer_id="ACT-0042",
        disposition=SecurityReviewDisposition.RELEASED,
        decided_at=NOW + timedelta(minutes=5),
        rationale="Verified false positive in isolated analysis.",
    )
    result = security_result(SecurityVerdict.MANUAL_REVIEW, manual_review=audit)
    clearance = SecurityClearedArtifact(
        artifact=result.artifact,
        document_id=result.document_id,
        security_result=result,
    )
    assert clearance.security_result.manual_review == audit
    assert result.allows_processing


def test_manual_review_rejection_does_not_permit_handoff() -> None:
    audit = SecurityManualReview(
        review_id="REV-000043",
        reviewer_id="ACT-0042",
        disposition=SecurityReviewDisposition.REJECTED,
        decided_at=NOW + timedelta(minutes=5),
        rationale="Embedded payload remains unsafe.",
    )
    result = security_result(SecurityVerdict.MANUAL_REVIEW, manual_review=audit)
    with pytest.raises(ValidationError, match="does not permit processing"):
        SecurityClearedArtifact(
            artifact=result.artifact,
            document_id=result.document_id,
            security_result=result,
        )


def test_security_clearance_is_bound_to_exact_artifact_hash() -> None:
    result = security_result(SecurityVerdict.ALLOW)
    changed = artifact_reference(content_hash=HASH_B)
    with pytest.raises(ValidationError, match="hash"):
        SecurityClearedArtifact(
            artifact=changed,
            document_id=result.document_id,
            security_result=result,
        )


def test_source_locator_requires_a_real_location() -> None:
    with pytest.raises(ValidationError, match="document location"):
        SourceLocator()


def test_source_derived_canonical_block_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="source"):
        Paragraph.model_validate(
            {
                "paragraph_id": "PAR-0042",
                "text": "source-derived",
                "order": 0,
            }
        )


def test_canonical_document_preserves_block_and_artifact_provenance() -> None:
    raw = artifact_reference()
    canonical_artifact = artifact_envelope(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type="canonical_document",
        inputs=[raw],
    )
    block_source = source_reference()
    document = CanonicalDocument(
        artifact=canonical_artifact,
        source_artifact=raw,
        document_id="DOC-003",
        bid_id=BID_ID,
        metadata=DocumentMetadata(parser="test-parser", parser_version="1.0.0"),
        pages=(
            Page(
                page_number=34,
                paragraphs=(
                    Paragraph(
                        paragraph_id="PAR-0042",
                        text="24/7 incident response must be provided",
                        order=0,
                        source=block_source,
                    ),
                ),
                ocr_applied=True,
                ocr_confidence=0.98,
            ),
        ),
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-003",
            filename="requirements.pdf",
            document_hash=HASH_A,
            locator=SourceLocator(whole_document=True),
        ),
    )
    assert document.pages[0].paragraphs[0].source.canonical_artifact_id
    invalid = document.model_dump()
    invalid["pages"][0]["paragraphs"][0]["source"]["locator"]["paragraph_id"] = "PAR-WRONG"
    with pytest.raises(ValidationError, match="exact block ID"):
        CanonicalDocument.model_validate(invalid)


def test_requirement_can_be_must_and_security() -> None:
    extracted = requirement()
    assert extracted.modality is RequirementModality.MUST
    assert extracted.category is RequirementCategory.SECURITY
    assert extracted.mandatory


def test_processing_state_is_separate_from_bid_business_state() -> None:
    opportunity = Opportunity(
        opportunity_id="OPP-000123",
        name="Managed SOC opportunity",
        customer="Example Customer",
        created_at=NOW,
    )
    bid = Bid(
        bid_id=BID_ID,
        opportunity_id=opportunity.opportunity_id,
        title="Managed SOC RFP",
        received_at=NOW,
        business_state=BidBusinessState.QUALIFYING,
    )
    run = ProcessingRun(
        run_id=RUN_ID,
        bid_id=bid.bid_id,
        stage=ProcessingStage.NORMALIZED,
        status=ProcessingStatus.IN_PROGRESS,
        started_at=NOW,
        updated_at=NOW,
    )
    assert bid.business_state is BidBusinessState.QUALIFYING
    assert run.stage is ProcessingStage.NORMALIZED


def test_completed_bid_decision_requires_an_audit_record() -> None:
    with pytest.raises(ValidationError, match="actor, timestamp, and rationale"):
        BidDecision(bid_id=BID_ID, status=BidDecisionStatus.GO)


def test_working_package_claim_requires_its_own_evidence() -> None:
    with pytest.raises(ValidationError, match="sources"):
        EvidencedStatement.model_validate(
            {
                "text": "The service requires 24/7 response.",
                "normalized_object_ids": ["REQ-000042"],
            }
        )


def test_normalized_bid_dataset_is_explicit_typed_fan_in() -> None:
    extraction_ref = artifact_reference(
        artifact_id=EXTRACTION_ARTIFACT_ID,
        artifact_type="extraction_result",
        content_hash=HASH_B,
    )
    normalized_artifact = artifact_envelope(
        artifact_id=NORMALIZED_ARTIFACT_ID,
        artifact_type="normalized_bid_dataset",
        inputs=[extraction_ref],
    )
    normalized = NormalizedObjectReference(
        bid_id=BID_ID,
        object_id="REQ-000042",
        object_type=NormalizedObjectType.REQUIREMENT,
        source_artifacts=(extraction_ref,),
        sources=(source_reference(),),
    )
    dataset = NormalizedBidDataset(
        artifact=normalized_artifact,
        bid_id=BID_ID,
        completeness=ExtractionCompleteness(
            expected_streams=(ExtractionStream.REQUIREMENT,),
            completed_streams=(ExtractionStream.REQUIREMENT,),
        ),
        requirements=(normalized,),
    )
    assert dataset.requirements[0].source_artifacts[0].artifact_id


def test_normalized_bid_dataset_rejects_cross_bid_reference() -> None:
    extraction_ref = artifact_reference(
        artifact_id=EXTRACTION_ARTIFACT_ID,
        artifact_type="extraction_result",
        content_hash=HASH_B,
    )
    normalized_artifact = artifact_envelope(
        artifact_id=NORMALIZED_ARTIFACT_ID,
        artifact_type="normalized_bid_dataset",
        inputs=[extraction_ref],
    )
    foreign = NormalizedObjectReference(
        bid_id=OTHER_BID_ID,
        object_id="REQ-000042",
        object_type=NormalizedObjectType.REQUIREMENT,
        source_artifacts=(
            artifact_reference(
                artifact_id=EXTRACTION_ARTIFACT_ID,
                bid_id=OTHER_BID_ID,
                artifact_type="extraction_result",
                content_hash=HASH_B,
            ),
        ),
        sources=(source_reference(bid_id=OTHER_BID_ID),),
    )
    with pytest.raises(ValidationError, match="dataset bid"):
        NormalizedBidDataset(
            artifact=normalized_artifact,
            bid_id=BID_ID,
            completeness=ExtractionCompleteness(
                expected_streams=(ExtractionStream.REQUIREMENT,),
                completed_streams=(ExtractionStream.REQUIREMENT,),
            ),
            requirements=(foreign,),
        )


def test_positive_capability_claim_without_evidence_fails() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        capability_match(evidence=[])


@pytest.mark.parametrize(
    "evidence",
    [
        approved_evidence(status=KnowledgeApprovalStatus.DRAFT),
        approved_evidence(valid_until=NOW - timedelta(days=1)),
    ],
)
def test_positive_capability_claim_requires_approved_current_knowledge(
    evidence: EvidenceReference,
) -> None:
    with pytest.raises(ValidationError, match="approved and valid"):
        capability_match(evidence=[evidence])


def test_positive_capability_claim_with_valid_governed_evidence_passes() -> None:
    match = capability_match()
    assert match.evidence[0].knowledge_item_id == "KNW-000018"


def test_coverage_counts_are_derived_and_cross_bid_is_rejected() -> None:
    coverage = CoverageResult(bid_id=BID_ID, matches=(capability_match(),))
    dumped = coverage.model_dump()
    assert dumped["total_requirements"] == 1
    assert dumped["supported"] == 1
    with pytest.raises(ValidationError, match="coverage bid"):
        CoverageResult(
            bid_id=BID_ID,
            matches=(capability_match(bid_id=OTHER_BID_ID),),
        )


def test_positive_compliance_status_requires_governed_evidence() -> None:
    with pytest.raises(ValidationError, match="governed evidence"):
        ComplianceItem(
            compliance_item_id="COMP-000042",
            bid_id=BID_ID,
            requirement_id="REQ-000042",
            status=ComplianceStatus.COMPLIANT,
            assessed_at=NOW,
            capability_ids=("CAP-018",),
            sources=(source_reference(),),
        )


def test_positive_compliance_status_rejects_unapproved_evidence() -> None:
    with pytest.raises(ValidationError, match="approved, current"):
        ComplianceItem(
            compliance_item_id="COMP-000042",
            bid_id=BID_ID,
            requirement_id="REQ-000042",
            status=ComplianceStatus.COMPLIANT,
            assessed_at=NOW,
            capability_ids=("CAP-018",),
            evidence=(approved_evidence(status=KnowledgeApprovalStatus.IN_REVIEW),),
            sources=(source_reference(),),
        )


def test_compliance_matrix_is_lineaged_to_normalized_dataset() -> None:
    normalized = artifact_envelope(
        artifact_id=NORMALIZED_ARTIFACT_ID,
        artifact_type="normalized_bid_dataset",
        inputs=[],
    ).as_reference()
    matrix_artifact = artifact_envelope(
        artifact_id="ART-20260727-000005",
        artifact_type="compliance_matrix",
        inputs=[normalized],
    )
    matrix = ComplianceMatrix(
        artifact=matrix_artifact,
        source_dataset=normalized,
        bid_id=BID_ID,
    )
    assert matrix.source_dataset.artifact_id == NORMALIZED_ARTIFACT_ID


def test_approved_knowledge_requires_governance_evidence() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        KnowledgeGovernance(
            owner_id="ACT-0042",
            approval_status=KnowledgeApprovalStatus.APPROVED,
            version=1,
            valid_from=NOW,
            review_cycle_days=180,
            classification=DataClassification.INTERNAL,
            source=KnowledgeSource(
                source_type=KnowledgeSourceType.POLICY,
                reference="policy://managed-soc",
            ),
        )


def test_working_package_claim_chain_and_dataset_lineage_are_explicit() -> None:
    normalized = artifact_envelope(
        artifact_id=NORMALIZED_ARTIFACT_ID,
        artifact_type="normalized_bid_dataset",
        inputs=[],
    ).as_reference()
    package_artifact = artifact_envelope(
        artifact_id="ART-20260727-000006",
        artifact_type="working_package",
        inputs=[normalized],
    )
    statement = EvidencedStatement(
        text="The service requires 24/7 response.",
        normalized_object_ids=("REQ-000042",),
        sources=(source_reference(),),
    )
    package = WorkingPackage(
        artifact=package_artifact,
        source_dataset=normalized,
        bid_id=BID_ID,
        generated_at=NOW,
        executive_overview=ExecutiveOverview(opportunity=statement),
    )
    assert package.executive_overview.opportunity == statement


def test_business_review_and_ai_validation_are_distinct_contracts() -> None:
    approval = Approval(
        review_id="REV-000042",
        bid_id=BID_ID,
        approver_id="ACT-0042",
        decision=ApprovalDecision.APPROVED,
        decided_at=NOW,
        rationale="Commercial and technical review completed.",
    )
    business_review = BusinessReview(
        review_id="REV-000042",
        bid_id=BID_ID,
        review_type=BusinessReviewType.FINAL,
        owner_id="ACT-0042",
        status=BusinessReviewStatus.COMPLETED,
        completed_at=NOW,
        approvals=(approval,),
    )
    ai_validation = HumanReview(
        review_id="REV-000043",
        bid_id=BID_ID,
        subject_type="requirement",
        subject_id="REQ-000042",
        decision=ReviewDecision.CONFIRMED,
        reviewer="ACT-0042",
        reviewed_at=NOW,
    )
    assert business_review.approvals[0].decision is ApprovalDecision.APPROVED
    assert ai_validation.decision is ReviewDecision.CONFIRMED


def test_valid_governed_knowledge_contains_owner_version_source_and_evidence() -> None:
    source = KnowledgeSource(
        source_type=KnowledgeSourceType.CERTIFICATION,
        reference="certificate://iso-27001",
    )
    governance = KnowledgeGovernance(
        owner_id="ACT-0042",
        approval_status=KnowledgeApprovalStatus.APPROVED,
        version=2,
        valid_from=NOW - timedelta(days=10),
        valid_until=NOW + timedelta(days=365),
        review_cycle_days=180,
        classification=DataClassification.INTERNAL,
        source=source,
        evidence=(
            KnowledgeEvidence(
                evidence_id="EVD-001",
                source=source,
                description="Current certification record.",
            ),
        ),
    )
    assert governance.owner_id == "ACT-0042"


def test_business_modules_cannot_select_an_llm_provider() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ModelRequirements.model_validate({"provider": "some-provider"})
