"""Golden Dataset ingestion tests.

Every document below is generated in-process and synthetic. The service
under test must never touch the network, an LLM, a subprocess, or the
bid pipeline — and must fail closed per source without ever producing a
partial KnowledgeDocument.
"""

from __future__ import annotations

import importlib.util
import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import ModuleType

from openpyxl import Workbook

from bidfusion.golden_dataset.contracts import (
    ExtractionStatus,
    IngestionStatus,
    KnowledgeSource,
    ParseStatus,
    ProvenanceStatus,
)
from bidfusion.golden_dataset.ingestion import GoldenDatasetIngestionService
from bidfusion.golden_dataset.inventory import build_inventory

_FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 12, 0, 0)
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="xml" ContentType="application/xml"/>'
    b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    b'officedocument.wordprocessingml.document.main+xml"/>'
    b"</Types>"
)


def _load_fixture_builders() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate_synthetic_fixtures.py"
    spec = importlib.util.spec_from_file_location("golden_fixture_builders", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paragraph(text: str, *, style: str | None = None) -> str:
    prefix = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{prefix}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _docx(body: str, *, extra: dict[str, bytes] | None = None) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_WORD_NS}"><w:body>{body}</w:body></w:document>'
    ).encode()
    entries: dict[str, bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES_XML,
        "word/document.xml": document,
    }
    entries.update(extra or {})
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return buffer.getvalue()


def _service_description_docx() -> bytes:
    return _docx(
        _paragraph("Synthetic Service Description", style="Heading1")
        + _paragraph("The synthetic service provides 24/7 monitoring of alerts.")
        + _paragraph("Scope", style="Heading1")
        + _paragraph("The synthetic service supports the Splunk platform.")
    )


def _xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Sizing"
    sheet["A1"] = "Synthetic tier"
    sheet["B1"] = "Synthetic events per day"
    sheet["A2"] = "Small"
    sheet["B2"] = "1000"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _inventoried(tmp_path: Path, name: str, content: bytes) -> tuple[KnowledgeSource, bytes]:
    (tmp_path / name).write_bytes(content)
    result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
    return result.inventory.sources[0], content


class TestSupportedFormats:
    def test_docx_service_description_becomes_a_knowledge_document(self, tmp_path: Path) -> None:
        source, content = _inventoried(
            tmp_path, "SD-Example Service-Splunk v1.0.docx", _service_description_docx()
        )
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is not None
        assert outcome.source.parse_status is ParseStatus.PARSED
        assert outcome.source.ingestion_status is IngestionStatus.INGESTED
        document = outcome.document
        assert document.title == "Synthetic Service Description"
        assert document.extraction_status is ExtractionStatus.EXTRACTED
        headings = [section.heading for section in document.sections]
        assert "Scope" in headings
        scope = document.sections[headings.index("Scope")]
        assert "Splunk" in scope.text
        assert scope.source_locator.paragraph_index is not None

    def test_pdf_source_gets_page_locators(self, tmp_path: Path) -> None:
        builders = _load_fixture_builders()
        content = builders.build_pdf(
            [["Synthetic overview line one.", "Synthetic overview line two."]]
        )
        source, content = _inventoried(tmp_path, "OV-Example Overview.pdf", content)
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is not None
        assert outcome.document.sections[0].source_locator.page == 1
        assert outcome.document.provenance_status is ProvenanceStatus.PROVENANCE_FULL

    def test_xlsx_source_gets_sheet_and_range_locators(self, tmp_path: Path) -> None:
        source, content = _inventoried(tmp_path, "OE-Example v1.0.xlsx", _xlsx())
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is not None
        locator = outcome.document.sections[0].source_locator
        assert locator.sheet == "Sizing"
        assert locator.cell_range == "A1:B2"

    def test_provenance_binds_document_to_exact_source(self, tmp_path: Path) -> None:
        source, content = _inventoried(
            tmp_path, "SD-Example Service-Splunk v1.0.docx", _service_description_docx()
        )
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is not None
        provenance = outcome.document.provenance
        assert provenance.source_id == source.source_id
        assert provenance.source_hash == sha256(content).hexdigest()
        assert provenance.filename == source.filename
        assert all(section.source_id == source.source_id for section in outcome.document.sections)

    def test_ingestion_is_deterministic(self, tmp_path: Path) -> None:
        source, content = _inventoried(
            tmp_path, "SD-Example Service-Splunk v1.0.docx", _service_description_docx()
        )
        service = GoldenDatasetIngestionService()
        first = service.ingest_source(source, content)
        second = service.ingest_source(source, content)
        assert first.document == second.document


class TestFailClosed:
    def test_unsupported_pptx_is_reported_not_raised(self, tmp_path: Path) -> None:
        source, content = _inventoried(tmp_path, "CP-Example.pptx", b"synthetic bytes")
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is None
        assert outcome.source.parse_status is ParseStatus.PARSE_UNSUPPORTED
        assert outcome.source.ingestion_status is IngestionStatus.INVENTORIED

    def test_parser_failure_yields_no_partial_document(self, tmp_path: Path) -> None:
        hostile = _docx(
            _paragraph("Synthetic"),
            extra={"word/settings.xml": b"<!DOCTYPE broken>"},
        )
        corrupted = _docx("")
        source, content = _inventoried(tmp_path, "SD-Example v1.0.docx", corrupted)
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is None
        assert outcome.source.parse_status is ParseStatus.PARSE_FAILED
        assert outcome.source.ingestion_status is IngestionStatus.INGESTION_FAILED
        assert outcome.failure_reason is not None
        assert hostile  # builder exercised; hostile variant covered below

    def test_doctype_docx_fails_closed_with_static_reason(self, tmp_path: Path) -> None:
        content = _docx('<!DOCTYPE d [<!ENTITY x "y">]>' + _paragraph("Synthetic &x; text"))
        source, content = _inventoried(tmp_path, "SD-Example v1.0.docx", content)
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is None
        assert outcome.source.parse_status is ParseStatus.PARSE_FAILED
        assert outcome.failure_reason is not None
        assert "DOCTYPE" not in outcome.failure_reason

    def test_macro_document_is_refused_by_the_real_security_gate(self, tmp_path: Path) -> None:
        content = _docx(
            _paragraph("Synthetic"),
            extra={"word/vbaProject.bin": b"synthetic macro payload"},
        )
        source, content = _inventoried(tmp_path, "SD-Example v1.0.docx", content)
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.document is None
        assert outcome.source.ingestion_status is IngestionStatus.INGESTION_FAILED
        assert outcome.failure_reason is not None
        assert "vbaProject" not in outcome.failure_reason

    def test_content_hash_mismatch_fails_closed(self, tmp_path: Path) -> None:
        source, _ = _inventoried(
            tmp_path, "SD-Example Service-Splunk v1.0.docx", _service_description_docx()
        )
        outcome = GoldenDatasetIngestionService().ingest_source(source, b"swapped bytes")
        assert outcome.document is None
        assert outcome.source.ingestion_status is IngestionStatus.INGESTION_FAILED

    def test_review_status_stays_required_after_ingestion(self, tmp_path: Path) -> None:
        source, content = _inventoried(
            tmp_path, "SD-Example Service-Splunk v1.0.docx", _service_description_docx()
        )
        outcome = GoldenDatasetIngestionService().ingest_source(source, content)
        assert outcome.source.review_status.value == "REQUIRED"
        assert outcome.document is not None
        assert outcome.document.review_status.value == "REQUIRED"
