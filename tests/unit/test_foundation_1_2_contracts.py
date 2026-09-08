"""Focused regression tests for Foundation 1.2 contract hardening."""

from __future__ import annotations

import operator
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from bidfusion.schemas import (
    ArtifactEnvelope,
    ArtifactProducer,
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    CapabilityMatch,
    CommercialExtractionResult,
    CommercialFinding,
    CommercialFindingKind,
    ComplianceExtractionResult,
    ComplianceFinding,
    ComplianceFindingKind,
    ComplianceItem,
    ComplianceStatus,
    Deadline,
    DeadlineExtractionResult,
    DeadlineKind,
    DocumentInventoryEntry,
    DocumentMetadata,
    DocumentRelationship,
    Entity,
    EntityExtractionResult,
    EntityKind,
    EvidencedStatement,
    EvidenceReference,
    ExecutionScope,
    ExtractedSecurityFinding,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ExtractionInfo,
    ExtractionStream,
    Formality,
    FormalityExtractionResult,
    FormalityKind,
    KnowledgeApprovalStatus,
    LLMRequest,
    MatchStatus,
    NormalizedBidDataset,
    NormalizedObjectReference,
    NormalizedObjectType,
    OCRBlock,
    OCRResult,
    ProcessingStatus,
    Requirement,
    RequirementCategory,
    RequirementExtractionResult,
    RequirementModality,
    RequirementsSummary,
    Scope,
    ScopeExtractionResult,
    ScopeKind,
    SecurityClearedArtifact,
    SecurityExtractionResult,
    SecurityFindingKind,
    SecurityResult,
    SecurityVerdict,
    SourceLocator,
    SourceReference,
)

ROOT = Path(__file__).resolve().parents[2]
BID_ID = "BID-2026-000123"
OTHER_BID_ID = "BID-2026-000999"
RUN_ID = "RUN-20260727-0001"
RAW_ARTIFACT_ID = "ART-20260727-000001"
CANONICAL_ARTIFACT_ID = "ART-20260727-000002"
EXTRACTION_ARTIFACT_ID = "ART-20260727-000003"
HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)


def artifact_reference(
    *,
    artifact_id: str = RAW_ARTIFACT_ID,
    bid_id: str = BID_ID,
    artifact_type: ArtifactType = ArtifactType.RAW_DOCUMENT,
    content_hash: str = HASH_A,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=RUN_ID,
        artifact_type=artifact_type,
        schema_version="1.0.0",
        content_ref=f"artifacts/{artifact_id}",
        content_hash=content_hash,
    )


def artifact_envelope(
    *,
    artifact_id: str,
    artifact_type: ArtifactType,
    inputs: list[ArtifactReference],
    bid_id: str = BID_ID,
) -> ArtifactEnvelope:
    return ArtifactEnvelope.model_validate(
        {
            "artifact_id": artifact_id,
            "bid_id": bid_id,
            "run_id": RUN_ID,
            "artifact_type": artifact_type,
            "schema_version": "1.0.0",
            "content_ref": f"artifacts/{artifact_id}",
            "content_hash": HASH_B,
            "producer": ArtifactProducer(component="foundation-test", version="1.2.0"),
            "input_artifacts": inputs,
            "created_at": NOW,
        }
    )


def source_reference(
    *,
    bid_id: str = BID_ID,
    canonical_artifact_id: str = CANONICAL_ARTIFACT_ID,
) -> SourceReference:
    return SourceReference(
        bid_id=bid_id,
        document_id="DOC-003",
        filename="requirements.pdf",
        document_hash=HASH_A,
        canonical_artifact_id=canonical_artifact_id,
        locator=SourceLocator(page=1, paragraph_id="PAR-001"),
        quote="The supplier must provide continuous monitoring.",
    )


def extraction_info() -> ExtractionInfo:
    return ExtractionInfo(
        method="llm",
        producer="focused-extractor",
        producer_version="1.2.0",
        model="gateway-route-7",
        prompt_version="v1",
    )


def extraction_result_data(
    *,
    input_artifact: ArtifactReference | None = None,
) -> dict[str, object]:
    canonical = input_artifact or artifact_reference(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        content_hash=HASH_B,
    )
    return {
        "artifact": artifact_envelope(
            artifact_id=EXTRACTION_ARTIFACT_ID,
            artifact_type=ArtifactType.EXTRACTION_RESULT,
            inputs=[canonical],
        ),
        "bid_id": BID_ID,
        "agent_name": "focused-extractor",
        "agent_version": "1.2.0",
        "document_ids": ["DOC-003"],
        "status": ProcessingStatus.COMPLETED,
        "started_at": NOW,
        "finished_at": NOW,
    }


def security_clearance() -> SecurityClearedArtifact:
    raw = artifact_reference()
    result = SecurityResult(
        bid_id=BID_ID,
        document_id="DOC-003",
        artifact=raw,
        content_hash=raw.content_hash,
        verdict=SecurityVerdict.ALLOW,
        scanner="foundation-test-scanner",
        scanner_version="1.0.0",
        policy_version="2026.07",
        decided_at=NOW,
    )
    return SecurityClearedArtifact(
        artifact=raw,
        document_id="DOC-003",
        security_result=result,
    )


def approved_evidence(*, checked_at: datetime = NOW) -> EvidenceReference:
    return EvidenceReference(
        knowledge_item_id="KNW-000018",
        capability_id="CAP-018",
        knowledge_version=3,
        approval_status=KnowledgeApprovalStatus.APPROVED,
        valid_from=NOW - timedelta(days=30),
        checked_at=checked_at,
        evidence_ids=("EVD-001",),
    )


def test_validated_contracts_reject_field_reassignment() -> None:
    raw = artifact_reference()
    envelope = artifact_envelope(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        inputs=[raw],
    )
    source = source_reference()
    match = CapabilityMatch(
        bid_id=BID_ID,
        requirement_id="REQ-000042",
        status=MatchStatus.UNKNOWN,
        confidence=0.5,
        evaluated_at=NOW,
    )

    for contract, field, value in (
        (security_clearance(), "artifact", raw),
        (envelope, "content_ref", "artifacts/reassigned"),
        (source, "quote", "reassigned evidence"),
        (match, "status", MatchStatus.NOT_SUPPORTED),
    ):
        with pytest.raises(ValidationError, match="frozen"):
            setattr(contract, field, value)


def test_artifact_lineage_rejects_ordinary_in_place_mutation() -> None:
    raw = artifact_reference()
    foreign = artifact_reference(bid_id=OTHER_BID_ID)
    envelope = artifact_envelope(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        inputs=[raw],
    )

    assert envelope.input_artifacts == (raw,)
    with pytest.raises(AttributeError):
        envelope.input_artifacts.append(foreign)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        envelope.input_artifacts.clear()  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        operator.setitem(envelope.input_artifacts, 0, foreign)  # type: ignore[call-overload]


def test_llm_scope_inputs_reject_ordinary_in_place_mutation() -> None:
    raw = artifact_reference()
    foreign = artifact_reference(bid_id=OTHER_BID_ID)
    request = LLMRequest.model_validate(
        {
            "request_id": "LLM-IMMUTABLE-001",
            "scope": {"bid_id": BID_ID},
            "input_artifacts": [raw],
        }
    )

    assert request.input_artifacts == (raw,)
    with pytest.raises(AttributeError):
        request.input_artifacts.append(foreign)  # type: ignore[attr-defined]


def test_positive_match_evidence_cannot_be_cleared() -> None:
    evidence = approved_evidence()
    match = CapabilityMatch.model_validate(
        {
            "bid_id": BID_ID,
            "requirement_id": "REQ-000042",
            "status": MatchStatus.SUPPORTED,
            "capability_id": "CAP-018",
            "confidence": 0.91,
            "evaluated_at": NOW,
            "evidence": [evidence],
        }
    )

    assert match.evidence == (evidence,)
    with pytest.raises(AttributeError):
        match.evidence.clear()  # type: ignore[attr-defined]


def test_normalized_dataset_cannot_append_cross_bid_content() -> None:
    extraction_ref = artifact_reference(
        artifact_id=EXTRACTION_ARTIFACT_ID,
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        content_hash=HASH_B,
    )
    normalized_artifact = artifact_envelope(
        artifact_id="ART-20260727-000005",
        artifact_type=ArtifactType.NORMALIZED_BID_DATASET,
        inputs=[extraction_ref],
    )
    local = NormalizedObjectReference(
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
        requirements=(local,),
    )
    foreign_artifact = artifact_reference(
        artifact_id="ART-20260727-000099",
        bid_id=OTHER_BID_ID,
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        content_hash=HASH_B,
    )
    foreign = NormalizedObjectReference(
        bid_id=OTHER_BID_ID,
        object_id="REQ-000099",
        object_type=NormalizedObjectType.REQUIREMENT,
        source_artifacts=(foreign_artifact,),
        sources=(source_reference(bid_id=OTHER_BID_ID),),
    )

    with pytest.raises(AttributeError):
        dataset.requirements.append(foreign)  # type: ignore[attr-defined]


def test_canonical_relationships_cannot_append_cross_bid_content() -> None:
    document = canonical_document()
    foreign = DocumentRelationship(
        bid_id=OTHER_BID_ID,
        from_document_id="DOC-003",
        to_document_id="DOC-999",
        kind="foreign",
    )

    with pytest.raises(AttributeError):
        document.relationships.append(foreign)  # type: ignore[attr-defined]


def test_evidenced_statement_sources_and_links_cannot_be_mutated() -> None:
    source = source_reference()
    statement = EvidencedStatement.model_validate(
        {
            "text": "The service requires 24/7 response.",
            "normalized_object_ids": ["REQ-000042"],
            "sources": [source],
        }
    )

    assert statement.sources == (source,)
    with pytest.raises(AttributeError):
        statement.sources.clear()  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        operator.setitem(  # type: ignore[call-overload]
            statement.normalized_object_ids,
            0,
            "REQ-000099",
        )


def test_validated_count_mappings_reject_item_assignment_and_clear() -> None:
    summary = RequirementsSummary(
        total=1,
        by_modality={RequirementModality.MUST: 1},
        by_category={RequirementCategory.SECURITY: 1},
    )

    with pytest.raises(TypeError, match="frozen mapping"):
        operator.setitem(summary.by_modality, RequirementModality.MUST, 0)
    with pytest.raises(TypeError, match="frozen mapping"):
        summary.by_category.clear()


def test_artifact_type_is_central_typed_and_serializes_stably() -> None:
    raw = artifact_reference()
    assert raw.artifact_type is ArtifactType.RAW_DOCUMENT
    assert raw.model_dump(mode="json")["artifact_type"] == "raw_document"

    invalid = raw.model_dump(mode="json")
    invalid["artifact_type"] = "raw_documnt"
    with pytest.raises(ValidationError, match="artifact_type"):
        ArtifactReference.model_validate(invalid)


def test_five_missing_payloads_have_minimal_source_bound_contracts() -> None:
    common = {
        "bid_id": BID_ID,
        "original_text": "Source observation.",
        "normalized_text": "Normalized observation.",
        "source": source_reference(),
        "confidence": 0.9,
        "extraction": extraction_info(),
    }
    payloads = (
        Formality.model_validate(
            {
                **common,
                "formality_id": "FORM-001",
                "kind": FormalityKind.REQUIRED_DOCUMENT,
            }
        ),
        Scope.model_validate(
            {
                **common,
                "scope_id": "SCOPE-001",
                "kind": ScopeKind.SERVICE,
            }
        ),
        CommercialFinding.model_validate(
            {
                **common,
                "commercial_finding_id": "COMM-001",
                "kind": CommercialFindingKind.PRICING_MODEL,
            }
        ),
        ExtractedSecurityFinding.model_validate(
            {
                **common,
                "security_finding_id": "SECF-001",
                "kind": SecurityFindingKind.CONTROL,
                "related_requirement_ids": ["REQ-000042"],
            }
        ),
        ComplianceFinding.model_validate(
            {
                **common,
                "compliance_finding_id": "COMPF-001",
                "kind": ComplianceFindingKind.REGULATION,
                "related_requirement_ids": ["REQ-000042"],
            }
        ),
    )
    assert all(payload.bid_id == BID_ID for payload in payloads)
    assert all(
        payload.source.canonical_artifact_id == CANONICAL_ARTIFACT_ID for payload in payloads
    )


def test_all_eight_extraction_streams_have_focused_result_contracts() -> None:
    requirement = Requirement(
        requirement_id="REQ-000042",
        bid_id=BID_ID,
        original_text="Continuous monitoring is mandatory.",
        modality=RequirementModality.MUST,
        category=RequirementCategory.SECURITY,
        confidence=0.95,
        source=source_reference(),
        extraction=extraction_info(),
    )
    deadline = Deadline(
        deadline_id="DEADLINE-001",
        bid_id=BID_ID,
        kind=DeadlineKind.SUBMISSION,
        due_at=NOW,
        source=source_reference(),
        confidence=0.95,
        extraction=extraction_info(),
    )
    entity = Entity(
        entity_id="ENTITY-001",
        bid_id=BID_ID,
        kind=EntityKind.ORGANIZATION,
        name="Example Customer",
        source=source_reference(),
        confidence=0.95,
        extraction=extraction_info(),
    )
    common = {
        "bid_id": BID_ID,
        "original_text": "Source observation.",
        "source": source_reference(),
        "confidence": 0.9,
        "extraction": extraction_info(),
    }
    formality = Formality.model_validate(
        {**common, "formality_id": "FORM-001", "kind": FormalityKind.REQUIRED_FORMAT}
    )
    scope = Scope.model_validate({**common, "scope_id": "SCOPE-001", "kind": ScopeKind.DELIVERY})
    commercial = CommercialFinding.model_validate(
        {
            **common,
            "commercial_finding_id": "COMM-001",
            "kind": CommercialFindingKind.BILLING_CONSTRAINT,
        }
    )
    security = ExtractedSecurityFinding.model_validate(
        {
            **common,
            "security_finding_id": "SECF-001",
            "kind": SecurityFindingKind.DATA_HANDLING,
        }
    )
    compliance = ComplianceFinding.model_validate(
        {
            **common,
            "compliance_finding_id": "COMPF-001",
            "kind": ComplianceFindingKind.STANDARD,
        }
    )
    base = extraction_result_data()
    results = (
        RequirementExtractionResult.model_validate({**base, "requirements": [requirement]}),
        DeadlineExtractionResult.model_validate({**base, "deadlines": [deadline]}),
        EntityExtractionResult.model_validate({**base, "entities": [entity]}),
        FormalityExtractionResult.model_validate({**base, "formalities": [formality]}),
        ScopeExtractionResult.model_validate({**base, "scope": [scope]}),
        CommercialExtractionResult.model_validate({**base, "findings": [commercial]}),
        SecurityExtractionResult.model_validate({**base, "findings": [security]}),
        ComplianceExtractionResult.model_validate({**base, "findings": [compliance]}),
    )

    assert tuple(result.stream for result in results) == tuple(ExtractionStream)
    payload_fields = (
        "requirements",
        "deadlines",
        "entities",
        "formalities",
        "scope",
        "findings",
        "findings",
        "findings",
    )
    possible_payload_fields = {
        "requirements",
        "deadlines",
        "entities",
        "formalities",
        "scope",
        "findings",
    }
    for result, payload_field in zip(results, payload_fields, strict=True):
        assert payload_field in type(result).model_fields
        assert sum(field in type(result).model_fields for field in possible_payload_fields) == 1


def test_extraction_result_rejects_source_missing_from_input_lineage() -> None:
    unrelated = artifact_reference(
        artifact_id="ART-20260727-000099",
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        content_hash=HASH_B,
    )
    formality = Formality(
        formality_id="FORM-001",
        bid_id=BID_ID,
        kind=FormalityKind.PORTAL_REQUIREMENT,
        original_text="Upload through the customer portal.",
        source=source_reference(),
        confidence=0.9,
        extraction=extraction_info(),
    )
    with pytest.raises(ValidationError, match="input lineage"):
        FormalityExtractionResult.model_validate(
            {
                **extraction_result_data(input_artifact=unrelated),
                "formalities": [formality],
            }
        )


def test_extraction_result_rejects_payload_source_outside_declared_documents() -> None:
    formality = Formality(
        formality_id="FORM-001",
        bid_id=BID_ID,
        kind=FormalityKind.REQUIRED_DOCUMENT,
        original_text="Provide the requested schedule.",
        source=source_reference(),
        confidence=0.9,
        extraction=extraction_info(),
    )
    result_data = extraction_result_data()
    result_data["document_ids"] = ["DOC-777"]

    with pytest.raises(ValidationError, match="declared document IDs"):
        FormalityExtractionResult.model_validate(
            {
                **result_data,
                "formalities": [formality],
            }
        )


def test_extraction_completeness_distinguishes_complete_partial_and_failed() -> None:
    expected = tuple(ExtractionStream)
    complete = ExtractionCompleteness(
        expected_streams=expected,
        completed_streams=expected,
    )
    partial = ExtractionCompleteness(
        expected_streams=(ExtractionStream.REQUIREMENT, ExtractionStream.SCOPE),
        completed_streams=(ExtractionStream.REQUIREMENT,),
    )
    failed = ExtractionCompleteness(
        expected_streams=(ExtractionStream.REQUIREMENT, ExtractionStream.SCOPE),
        completed_streams=(ExtractionStream.REQUIREMENT,),
        failed_streams=(ExtractionStream.SCOPE,),
    )

    assert complete.state is ExtractionCompletenessState.COMPLETE
    assert partial.state is ExtractionCompletenessState.PARTIAL
    assert failed.state is ExtractionCompletenessState.FAILED


def test_extraction_completeness_rejects_unexpected_duplicate_or_conflicting_streams() -> None:
    with pytest.raises(ValidationError, match="unexpected stream"):
        ExtractionCompleteness(
            expected_streams=(ExtractionStream.REQUIREMENT,),
            completed_streams=(ExtractionStream.SCOPE,),
        )
    with pytest.raises(ValidationError, match="duplicate streams"):
        ExtractionCompleteness(
            expected_streams=(ExtractionStream.REQUIREMENT, ExtractionStream.REQUIREMENT),
        )
    with pytest.raises(ValidationError, match="only one completion outcome"):
        ExtractionCompleteness(
            expected_streams=(ExtractionStream.REQUIREMENT,),
            completed_streams=(ExtractionStream.REQUIREMENT,),
            failed_streams=(ExtractionStream.REQUIREMENT,),
        )


def canonical_document(*, relationship_bid_id: str = BID_ID) -> CanonicalDocument:
    raw = artifact_reference()
    canonical = artifact_envelope(
        artifact_id=CANONICAL_ARTIFACT_ID,
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        inputs=[raw],
    )
    return CanonicalDocument(
        artifact=canonical,
        source_artifact=raw,
        document_id="DOC-003",
        bid_id=BID_ID,
        metadata=DocumentMetadata(parser="test-parser", parser_version="1.0.0"),
        relationships=(
            DocumentRelationship(
                bid_id=relationship_bid_id,
                from_document_id="DOC-003",
                to_document_id="DOC-777",
                kind="supersedes",
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


def test_document_relationship_is_explicitly_bid_scoped() -> None:
    assert canonical_document().relationships[0].bid_id == BID_ID
    with pytest.raises(ValidationError, match="canonical document bid"):
        canonical_document(relationship_bid_id=OTHER_BID_ID)


def test_llm_request_enforces_execution_scope_for_bid_bound_inputs() -> None:
    raw = artifact_reference()
    request = LLMRequest(
        request_id="LLM-REQ-001",
        scope=ExecutionScope(bid_id=BID_ID),
        input_artifacts=(raw,),
    )
    assert request.scope is not None and request.scope.bid_id == BID_ID

    with pytest.raises(ValidationError, match="execution scope bid"):
        LLMRequest(
            request_id="LLM-REQ-002",
            scope=ExecutionScope(bid_id=OTHER_BID_ID),
            input_artifacts=(raw,),
        )
    with pytest.raises(ValidationError, match="require an execution scope"):
        LLMRequest(request_id="LLM-REQ-003", input_artifacts=(raw,))

    unscoped = LLMRequest(request_id="LLM-REQ-004", prompt="General non-bid request.")
    assert unscoped.scope is None


def test_positive_compliance_rejects_evidence_checked_after_assessment() -> None:
    with pytest.raises(ValidationError, match="checked no later than assessment"):
        ComplianceItem(
            compliance_item_id="COMP-000042",
            bid_id=BID_ID,
            requirement_id="REQ-000042",
            status=ComplianceStatus.COMPLIANT,
            assessed_at=NOW,
            capability_ids=("CAP-018",),
            evidence=(approved_evidence(checked_at=NOW + timedelta(days=1)),),
            sources=(source_reference(),),
        )


@pytest.mark.parametrize(
    ("security_status", "processing_status"),
    [
        (SecurityVerdict.BLOCK, ProcessingStatus.COMPLETED),
        (SecurityVerdict.QUARANTINE, ProcessingStatus.IN_PROGRESS),
        (SecurityVerdict.MANUAL_REVIEW, ProcessingStatus.COMPLETED),
        (SecurityVerdict.BLOCK, ProcessingStatus.REQUIRES_REVIEW),
    ],
)
def test_inventory_rejects_contradictory_security_and_processing_states(
    security_status: SecurityVerdict,
    processing_status: ProcessingStatus,
) -> None:
    raw = artifact_reference()
    with pytest.raises(ValidationError, match="downstream|terminal"):
        DocumentInventoryEntry(
            bid_id=BID_ID,
            document_id="DOC-003",
            artifact=raw,
            filename="requirements.pdf",
            file_type="pdf",
            mime_type="application/pdf",
            hash=raw.content_hash,
            size=123,
            security_status=security_status,
            processing_status=processing_status,
        )


def valid_ocr_result_data() -> dict[str, object]:
    raw = artifact_reference()
    block = OCRBlock(
        block_id="BLOCK-001",
        order=0,
        text="Continuous monitoring is mandatory.",
        confidence=0.99,
        source=SourceReference(
            bid_id=BID_ID,
            document_id="DOC-003",
            filename="requirements.pdf",
            document_hash=HASH_A,
            locator=SourceLocator(page=1, block_id="BLOCK-001"),
        ),
    )
    return {
        "artifact": artifact_envelope(
            artifact_id="ART-20260727-000004",
            artifact_type=ArtifactType.OCR_RESULT,
            inputs=[raw],
        ),
        "bid_id": BID_ID,
        "document_id": "DOC-003",
        "source_artifact": raw,
        "blocks": [block],
        "detected_language": "en",
    }


def first_ocr_block(data: dict[str, object]) -> OCRBlock:
    blocks = data["blocks"]
    if not isinstance(blocks, list) or not blocks or not isinstance(blocks[0], OCRBlock):
        raise AssertionError("test fixture must contain at least one OCRBlock")
    return blocks[0]


def test_ocr_rejects_canonicalized_hash_mismatched_and_duplicate_blocks() -> None:
    canonicalized = valid_ocr_result_data()
    canonicalized_block = first_ocr_block(canonicalized).model_dump()
    canonicalized_block["source"]["canonical_artifact_id"] = CANONICAL_ARTIFACT_ID
    canonicalized["blocks"] = [canonicalized_block]
    with pytest.raises(ValidationError, match="precede canonical mapping"):
        OCRResult.model_validate(canonicalized)

    hash_mismatched = valid_ocr_result_data()
    hash_mismatched_block = first_ocr_block(hash_mismatched).model_dump()
    hash_mismatched_block["source"]["document_hash"] = HASH_B
    hash_mismatched["blocks"] = [hash_mismatched_block]
    with pytest.raises(ValidationError, match="source artifact hash"):
        OCRResult.model_validate(hash_mismatched)

    duplicate = valid_ocr_result_data()
    duplicate_block = first_ocr_block(duplicate)
    duplicate["blocks"] = [duplicate_block, duplicate_block]
    with pytest.raises(ValidationError, match="block IDs must be unique"):
        OCRResult.model_validate(duplicate)


@pytest.mark.allow_subprocess
def test_checked_in_json_schemas_match_exported_models(tmp_path: Path) -> None:
    schema_dir = ROOT / "schemas"
    subprocess.run(
        [sys.executable, "scripts/export_schemas.py", str(tmp_path)],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "src"),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    checked_in = {path.name: path.read_text() for path in schema_dir.glob("*.json")}
    generated = {path.name: path.read_text() for path in tmp_path.glob("*.json")}
    assert checked_in == generated
