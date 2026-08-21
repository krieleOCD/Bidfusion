"""Deterministic filename classification tests.

All filenames below are synthetic. They imitate the *naming scheme* of
internal documents without reproducing any real document's content.
"""

from __future__ import annotations

import pytest

from bidfusion.golden_dataset.classification import classify_filename
from bidfusion.golden_dataset.contracts import DocumentType, ServiceFamily, Technology


class TestDocumentTypePrefixes:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("SD-Example Service-Splunk v1.0.docx", DocumentType.SERVICE_DESCRIPTION),
            ("QA-Example Service - Vectra v1.0.docx", DocumentType.QA_TECHNOLOGY_GUIDANCE),
            (
                "SAP-Example - phased activation v1.0.docx",
                DocumentType.SERVICE_ACTIVATION_PROCEDURE,
            ),
            ("SI-Example - Handover v1.0.docx", DocumentType.SERVICE_INSTRUCTION),
            ("CL-Example Check List v1.0.docx", DocumentType.CHECKLIST),
            ("CP-Example Presentation.pptx", DocumentType.CUSTOMER_PRESENTATION),
            ("DS-Example - MDR.pdf", DocumentType.DATASHEET),
            ("OV-Example Overview.docx", DocumentType.OVERVIEW),
            ("PO-Example Pricing v1.0.xlsx", DocumentType.PRICING_COMMERCIAL),
            ("PO - Example.xlsx", DocumentType.PRICING_COMMERCIAL),
            ("OE-Example v1.0.xlsx", DocumentType.OFFERING_ESTIMATE),
            ("OH-Example v1.0.docx", DocumentType.OPERATIONAL_HANDBOOK),
            ("SC-Example v1.0.docx", DocumentType.SERVICE_CATALOGUE),
            ("SOW-Example v1.0.docx", DocumentType.STATEMENT_OF_WORK),
        ],
    )
    def test_known_prefixes_map_to_document_types(
        self, filename: str, expected: DocumentType
    ) -> None:
        assert classify_filename(filename).document_type is expected

    def test_unknown_prefix_is_unknown_not_guessed(self) -> None:
        assert classify_filename("SR-Example report.pdf").document_type is DocumentType.UNKNOWN

    def test_no_prefix_is_unknown(self) -> None:
        assert classify_filename("Example Notes.docx").document_type is DocumentType.UNKNOWN

    def test_statement_of_work_token_without_prefix(self) -> None:
        classified = classify_filename(
            "Example Service Sentinel - Professional Services Statement of Work.docx"
        )
        assert classified.document_type is DocumentType.STATEMENT_OF_WORK


class TestTechnology:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            (
                "QA-Managed Threat Detection - Microsoft Defender XDR v1.0.docx",
                Technology.MICROSOFT_DEFENDER_XDR,
            ),
            (
                "SI-Example - Microsoft 365 Defender - Applications.pdf",
                Technology.MICROSOFT_DEFENDER_XDR,
            ),
            (
                "QA-Managed Threat Detection - Microsoft Sentinel v1.0.docx",
                Technology.MICROSOFT_SENTINEL,
            ),
            ("SD-Managed Threat Detection-Microsoft v1.0.docx", Technology.MICROSOFT_GENERIC),
            (
                "SAP-Managed Threat Detection - Palo Alto Cortex XDR endpoint v1.0.docx",
                Technology.PALO_ALTO_CORTEX_XDR,
            ),
            (
                "SAP-Managed Threat Detection - Palo Alto Cortex XSIAM v1.0.docx",
                Technology.PALO_ALTO_XSIAM,
            ),
            (
                "SAP-Example - Palo Alto Cortex - Migration from XDR to XSIAM v1.0.docx",
                Technology.PALO_ALTO_XSIAM,
            ),
            ("SD-Managed Threat Detection-Splunk v1.0.docx", Technology.SPLUNK),
            ("SD-Managed Threat Detection-Vectra v1.0.docx", Technology.VECTRA),
            (
                "OV-Managed Threat Response [isolation] v1.0.docx",
                Technology.MANAGED_THREAT_RESPONSE,
            ),
            (
                "SD-eBonding for ITSM systems - Service Description v1.0.docx",
                Technology.ITSM_EBONDING,
            ),
            ("SC-Managed Threat Detection v1.0.docx", Technology.GENERIC_MTD),
            ("ZZ-Unrelated Document.docx", Technology.UNKNOWN),
        ],
    )
    def test_technology_tokens(self, filename: str, expected: Technology) -> None:
        assert classify_filename(filename).technology is expected


class TestServiceFamily:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            (
                "SD-Managed Threat Detection-Splunk v1.0.docx",
                ServiceFamily.MANAGED_THREAT_DETECTION,
            ),
            (
                "SD-Managed Threat Response [isolation] v1.0.docx",
                ServiceFamily.MANAGED_THREAT_RESPONSE,
            ),
            ("SD-eBonding for ITSM systems v1.0.docx", ServiceFamily.EBONDING_ITSM),
            (
                "SI-MTD for Microsoft Sentinel - Azure DevOps v1.2.docx",
                ServiceFamily.MANAGED_THREAT_DETECTION,
            ),
            ("ZZ-Unrelated Document.docx", ServiceFamily.UNKNOWN),
        ],
    )
    def test_service_family_tokens(self, filename: str, expected: ServiceFamily) -> None:
        assert classify_filename(filename).service_family is expected


class TestVersion:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("SD-Example v2026.2.1.docx", "2026.2.1"),
            ("SD-Example v2026.2.docx", "2026.2"),
            ("QA-Example v2025.1.docx", "2025.1"),
            ("SI-Example v.2.1.pdf", "2.1"),
            ("SI-Example v0.x.docx", "0.x"),
            ("SI-Example v0.1.docx", "0.1"),
            ("OH-Example [isolation] 3.1.docx", "3.1"),
            ("SD-Example v4.1.docx", "4.1"),
            ("OV-Example Overview.docx", None),
        ],
    )
    def test_version_extraction(self, filename: str, expected: str | None) -> None:
        assert classify_filename(filename).version == expected

    def test_classification_is_deterministic(self) -> None:
        name = "SD-Managed Threat Detection-Splunk v2026.2.docx"
        assert classify_filename(name) == classify_filename(name)
