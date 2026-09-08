"""Contract tests for the Golden Dataset domain models.

Every fixture here is synthetic. No test in this module may read real
internal documents or reference the local MTD source directory.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ClaimStatus,
    ConfidenceBand,
    DocumentType,
    EvidenceReference,
    ExtractionStatus,
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeDocument,
    KnowledgeProvenance,
    KnowledgeSection,
    KnowledgeSource,
    KnowledgeSourceLocator,
    MatchCandidate,
    MatchStatus,
    ParseStatus,
    ParseSupport,
    ProvenanceStatus,
    RequirementCandidate,
    ServiceFamily,
    Technology,
    confirm_claim,
    reject_claim,
)

_HASH = "a" * 64


def _locator() -> KnowledgeSourceLocator:
    return KnowledgeSourceLocator(paragraph_index=3)


def _evidence() -> EvidenceReference:
    return EvidenceReference(
        source_id="GKS-000000000001",
        section_id="SEC-0001",
        locator=_locator(),
        source_version="2026.1",
    )


def _claim(**overrides: object) -> CapabilityClaim:
    fields: dict[str, object] = {
        "claim_id": "GCL-000000000001",
        "service_family": ServiceFamily.MANAGED_THREAT_DETECTION,
        "technology": Technology.MICROSOFT_SENTINEL,
        "capability": CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,
        "statement": "Synthetic: the service monitors Microsoft Sentinel.",
        "evidence_refs": (_evidence(),),
        "confidence_band": ConfidenceBand.MEDIUM,
    }
    fields.update(overrides)
    return CapabilityClaim.model_validate(fields)


class TestKnowledgeSourceLocator:
    def test_requires_at_least_one_location(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeSourceLocator()

    def test_accepts_single_locator_kinds(self) -> None:
        assert KnowledgeSourceLocator(page=2).page == 2
        assert KnowledgeSourceLocator(paragraph_index=0).paragraph_index == 0
        assert KnowledgeSourceLocator(sheet="Sizing", cell_range="A1:B2").sheet == "Sizing"
        assert KnowledgeSourceLocator(line_start=1, line_end=4).line_end == 4
        assert KnowledgeSourceLocator(whole_document=True).whole_document is True

    def test_line_range_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeSourceLocator(line_start=9, line_end=3)


class TestKnowledgeSource:
    def _source(self, **overrides: object) -> KnowledgeSource:
        fields: dict[str, object] = {
            "source_id": "GKS-000000000001",
            "filename": "SD-Synthetic Service-Example v1.0.docx",
            "extension": "docx",
            "file_size": 1234,
            "source_hash": _HASH,
            "service_family": ServiceFamily.MANAGED_THREAT_DETECTION,
            "technology": Technology.SPLUNK,
            "document_type": DocumentType.SERVICE_DESCRIPTION,
            "version": "1.0",
            "parse_support": ParseSupport.SUPPORTED,
            "parse_status": ParseStatus.NOT_PARSED,
            "ingestion_status": IngestionStatus.INVENTORIED,
            "review_status": HumanReviewStatus.REQUIRED,
            "provenance_id": "GPV-000000000001",
        }
        fields.update(overrides)
        return KnowledgeSource.model_validate(fields)

    def test_holds_declared_inventory_fields(self) -> None:
        source = self._source()
        assert source.source_id == "GKS-000000000001"
        assert source.parse_support is ParseSupport.SUPPORTED

    def test_has_no_source_path_field(self) -> None:
        with pytest.raises(ValidationError):
            self._source(source_path="/home/someone/private/dataset")

    def test_serialization_carries_no_path_like_field(self) -> None:
        payload = self._source().model_dump_json()
        assert "source_path" not in payload
        assert "/" not in self._source().filename or "\\" not in payload


class TestCapabilityClaim:
    def test_starts_extracted_unverified_by_default(self) -> None:
        claim = _claim()
        assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED
        assert claim.human_review_status is HumanReviewStatus.REQUIRED

    def test_requires_evidence(self) -> None:
        with pytest.raises(ValidationError):
            _claim(evidence_refs=())

    def test_cannot_be_born_human_confirmed(self) -> None:
        with pytest.raises(ValidationError):
            _claim(status=ClaimStatus.HUMAN_CONFIRMED)

    def test_confirm_claim_is_the_only_way_to_human_confirmed(self) -> None:
        confirmed = confirm_claim(_claim(), reviewer="ACT-0001")
        assert confirmed.status is ClaimStatus.HUMAN_CONFIRMED
        assert confirmed.human_review_status is HumanReviewStatus.CONFIRMED
        assert confirmed.reviewed_by == "ACT-0001"

    def test_reject_claim_records_rejection(self) -> None:
        rejected = reject_claim(_claim(), reviewer="ACT-0001")
        assert rejected.status is ClaimStatus.REJECTED
        assert rejected.human_review_status is HumanReviewStatus.REJECTED

    def test_confirmation_requires_a_reviewer(self) -> None:
        with pytest.raises(ValueError, match="reviewer"):
            confirm_claim(_claim(), reviewer="   ")


class TestKnowledgeDocument:
    def test_holds_sections_with_provenance(self) -> None:
        section = KnowledgeSection(
            section_id="SEC-0001",
            heading="Synthetic heading",
            text="Synthetic section text.",
            source_locator=_locator(),
            source_id="GKS-000000000001",
        )
        document = KnowledgeDocument(
            knowledge_document_id="GKD-000000000001",
            source_id="GKS-000000000001",
            schema_version="1.0.0",
            title="Synthetic Service Description",
            service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
            technology=Technology.SPLUNK,
            document_type=DocumentType.SERVICE_DESCRIPTION,
            source_version="1.0",
            sections=(section,),
            provenance=KnowledgeProvenance(
                source_id="GKS-000000000001",
                filename="SD-Synthetic Service-Example v1.0.docx",
                source_hash=_HASH,
                document_version="1.0",
                locator=KnowledgeSourceLocator(whole_document=True),
            ),
            extraction_status=ExtractionStatus.EXTRACTED,
            review_status=HumanReviewStatus.REQUIRED,
            provenance_status=ProvenanceStatus.PROVENANCE_FULL,
        )
        assert document.sections[0].heading == "Synthetic heading"
        assert document.provenance.source_hash == _HASH

    def test_sections_must_reference_the_document_source(self) -> None:
        foreign_section = KnowledgeSection(
            section_id="SEC-0001",
            heading=None,
            text="Text",
            source_locator=_locator(),
            source_id="GKS-999999999999",
        )
        with pytest.raises(ValidationError):
            KnowledgeDocument(
                knowledge_document_id="GKD-000000000001",
                source_id="GKS-000000000001",
                schema_version="1.0.0",
                title="Synthetic",
                service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
                technology=Technology.SPLUNK,
                document_type=DocumentType.SERVICE_DESCRIPTION,
                source_version=None,
                sections=(foreign_section,),
                provenance=KnowledgeProvenance(
                    source_id="GKS-000000000001",
                    filename="synthetic.docx",
                    source_hash=_HASH,
                    document_version=None,
                    locator=KnowledgeSourceLocator(whole_document=True),
                ),
                extraction_status=ExtractionStatus.EXTRACTED,
                review_status=HumanReviewStatus.REQUIRED,
                provenance_status=ProvenanceStatus.PROVENANCE_FULL,
            )


class TestMatching:
    def test_requirement_candidate_carries_optional_hints(self) -> None:
        requirement = RequirementCandidate(
            requirement_id="DEMO-REQ-001",
            text="Synthetic requirement text.",
            technology_hint=Technology.SPLUNK,
            capability_hint=CapabilityCategory.SPLUNK_SUPPORT,
        )
        assert requirement.technology_hint is Technology.SPLUNK

    def test_match_candidate_requires_claim_for_matched_status(self) -> None:
        with pytest.raises(ValidationError):
            MatchCandidate(
                requirement_id="DEMO-REQ-001",
                claim_id=None,
                match_status=MatchStatus.MATCHED,
                rationale="Synthetic rationale.",
                evidence_refs=(_evidence(),),
                human_review_status=HumanReviewStatus.REQUIRED,
            )

    def test_gap_match_carries_no_claim(self) -> None:
        candidate = MatchCandidate(
            requirement_id="DEMO-REQ-002",
            claim_id=None,
            match_status=MatchStatus.GAP,
            rationale="Synthetic rationale.",
            evidence_refs=(),
            human_review_status=HumanReviewStatus.REQUIRED,
        )
        assert candidate.claim_id is None
