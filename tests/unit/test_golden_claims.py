"""Rule-based capability claim extraction tests — synthetic documents only."""

from __future__ import annotations

import pytest

from bidfusion.golden_dataset.claims import MAX_CLAIMS, extract_claims
from bidfusion.golden_dataset.contracts import (
    ClaimStatus,
    DocumentType,
    ExtractionStatus,
    HumanReviewStatus,
    KnowledgeDocument,
    KnowledgeProvenance,
    KnowledgeSection,
    KnowledgeSourceLocator,
    ProvenanceStatus,
    ServiceFamily,
    Technology,
)

_HASH = "c" * 64


def _document(
    *,
    source_id: str = "GKS-00000000000a",
    technology: Technology = Technology.MICROSOFT_SENTINEL,
    document_type: DocumentType = DocumentType.SERVICE_DESCRIPTION,
    service_family: ServiceFamily = ServiceFamily.MANAGED_THREAT_DETECTION,
    sections: tuple[tuple[str | None, str], ...] = (),
    version: str | None = "1.0",
) -> KnowledgeDocument:
    knowledge_sections = tuple(
        KnowledgeSection(
            section_id=f"SEC-{index:04d}",
            heading=heading,
            text=text,
            source_locator=KnowledgeSourceLocator(paragraph_index=index),
            source_id=source_id,
        )
        for index, (heading, text) in enumerate(sections)
    )
    return KnowledgeDocument(
        knowledge_document_id=f"GKD-{source_id[-12:]}",
        source_id=source_id,
        schema_version="1.0.0",
        title="Synthetic document",
        service_family=service_family,
        technology=technology,
        document_type=document_type,
        source_version=version,
        sections=knowledge_sections,
        provenance=KnowledgeProvenance(
            source_id=source_id,
            filename="SD-Synthetic v1.0.docx",
            source_hash=_HASH,
            document_version=version,
            locator=KnowledgeSourceLocator(whole_document=True),
        ),
        extraction_status=ExtractionStatus.EXTRACTED,
        review_status=HumanReviewStatus.REQUIRED,
        provenance_status=ProvenanceStatus.PROVENANCE_FULL,
    )


def _sentinel_document() -> KnowledgeDocument:
    return _document(
        sections=(
            ("Service scope", "The synthetic service monitors Microsoft Sentinel workspaces."),
            ("Operations", "Alerts are handled around the clock, 24/7."),
        )
    )


class TestEvidenceDiscipline:
    def test_claims_carry_evidence_into_matching_sections(self) -> None:
        claims = extract_claims((_sentinel_document(),))
        sentinel = [c for c in claims if c.capability.value == "microsoft_sentinel_support"]
        assert len(sentinel) == 1
        evidence = sentinel[0].evidence_refs
        assert evidence
        assert all(ref.source_id == "GKS-00000000000a" for ref in evidence)
        assert all(ref.source_version == "1.0" for ref in evidence)

    def test_no_matching_content_produces_no_claim(self) -> None:
        document = _document(
            technology=Technology.SPLUNK,
            sections=(("Scope", "This synthetic text never mentions the platform token."),),
        )
        claims = extract_claims((document,))
        assert all(claim.capability.value != "splunk_support" for claim in claims)

    def test_documents_without_sections_produce_no_claims(self) -> None:
        assert extract_claims((_document(sections=()),)) == ()

    def test_every_claim_starts_extracted_unverified(self) -> None:
        for claim in extract_claims((_sentinel_document(),)):
            assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED
            assert claim.human_review_status is HumanReviewStatus.REQUIRED


class TestNegativeContextGuard:
    """Negative or non-capability context must never yield a positive claim.

    Conservative false negatives are acceptable for the pilot; false
    positive capability claims are not.
    """

    def _sentinel_doc(self, *sections: tuple[str | None, str]) -> KnowledgeDocument:
        return _document(sections=tuple(sections))

    def test_positive_support_still_produces_a_claim(self) -> None:
        doc = self._sentinel_doc(
            ("Scope", "The service monitors Microsoft Sentinel workspaces continuously.")
        )
        claims = extract_claims((doc,))
        assert [c.capability.value for c in claims] == ["microsoft_sentinel_support"]

    @pytest.mark.parametrize(
        "text",
        [
            "Microsoft Sentinel is not supported by this service.",
            "The service does not support Microsoft Sentinel.",
            "Microsoft Sentinel is unsupported in this offering.",
            "Microsoft Sentinel is not available in this region.",
            "Support for Microsoft Sentinel requires a third party.",
            "Microsoft Sentinel integration: third-party required.",
            "Third-party support is required for Microsoft Sentinel.",
            "For Microsoft Sentinel, third party services are required.",
            "Microsoft Sentinel is shown only as an example.",
            "Microsoft Sentinel appears here for example purposes.",
            "Microsoft Sentinel is mentioned only for completeness.",
            "Microsoft Sentinel is excluded from this service.",
        ],
    )
    def test_negative_sentinel_context_produces_no_claim(self, text: str) -> None:
        claims = extract_claims((self._sentinel_doc((None, text)),))
        assert claims == ()

    def test_out_of_scope_isolation_produces_no_claim(self) -> None:
        doc = _document(
            technology=Technology.MANAGED_THREAT_RESPONSE,
            service_family=ServiceFamily.MANAGED_THREAT_RESPONSE,
            sections=(
                (None, "Endpoint isolation is outside the scope of this service."),
                (None, "This service does not cover isolation of servers."),
            ),
        )
        assert extract_claims((doc,)) == ()

    def test_unavailable_around_the_clock_monitoring_produces_no_claim(self) -> None:
        doc = self._sentinel_doc((None, "Monitoring on a 24/7 basis is not available."))
        assert extract_claims((doc,)) == ()

    def test_heading_only_technology_mention_produces_no_claim(self) -> None:
        doc = self._sentinel_doc(
            ("Microsoft Sentinel", "This body text describes something unrelated entirely.")
        )
        assert extract_claims((doc,)) == ()

    def test_heading_with_positive_supporting_body_produces_a_claim(self) -> None:
        doc = self._sentinel_doc(
            ("Microsoft Sentinel", "The service operates Microsoft Sentinel for the customer.")
        )
        claims = extract_claims((doc,))
        assert [c.capability.value for c in claims] == ["microsoft_sentinel_support"]

    def test_one_negative_and_one_clean_occurrence_still_counts_as_evidence(self) -> None:
        text = (
            "Legacy Microsoft Sentinel workspaces are not supported under the old "
            "contract terms, as detailed in the appendix of the previous edition. "
            "The current service operates Microsoft Sentinel for every customer."
        )
        claims = extract_claims((self._sentinel_doc((None, text)),))
        assert [c.capability.value for c in claims] == ["microsoft_sentinel_support"]

    def test_guarded_extraction_is_deterministic(self) -> None:
        doc = self._sentinel_doc(
            (None, "Microsoft Sentinel is not supported."),
            (None, "The service operates Microsoft Sentinel continuously."),
        )
        assert extract_claims((doc,)) == extract_claims((doc,))

    def test_guarded_claims_remain_extracted_unverified(self) -> None:
        doc = self._sentinel_doc((None, "The service operates Microsoft Sentinel."))
        for claim in extract_claims((doc,)):
            assert claim.status is ClaimStatus.EXTRACTED_UNVERIFIED


class TestRules:
    def test_around_the_clock_monitoring_is_detected(self) -> None:
        claims = extract_claims((_sentinel_document(),))
        assert any(claim.capability.value == "24_7_monitoring" for claim in claims)

    def test_isolation_rule_requires_threat_response_family(self) -> None:
        mtr = _document(
            source_id="GKS-00000000000b",
            technology=Technology.MANAGED_THREAT_RESPONSE,
            service_family=ServiceFamily.MANAGED_THREAT_RESPONSE,
            sections=(("Response", "Endpoint isolation is performed on confirmed incidents."),),
        )
        claims = extract_claims((mtr,))
        assert any(claim.capability.value == "incident_isolation" for claim in claims)

    def test_extraction_is_deterministic_and_capped(self) -> None:
        documents = (_sentinel_document(),)
        first = extract_claims(documents)
        second = extract_claims(documents)
        assert first == second
        assert len(first) <= MAX_CLAIMS
