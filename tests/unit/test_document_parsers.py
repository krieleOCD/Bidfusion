"""Tests for the MVP document parsers and canonical assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from bidfusion.document_understanding.canonical import (
    ClearedContentMismatchError,
    DocumentParser,
    DocumentParsingError,
    ParsedContent,
    ParserError,
    UnsupportedDocumentError,
    build_canonical_document,
)
from bidfusion.document_understanding.parsers import (
    PdfTextParser,
    PlainTextParser,
    XlsxTableParser,
    parser_for,
)
from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    SecurityClearedArtifact,
    SecurityResult,
    SecurityVerdict,
    TableCell,
)
from bidfusion.security import DeterministicPreflightScanner, decide_document

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "synthetic"
BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
DOCUMENT_ID = "DOC-001"
RAW_ARTIFACT_ID = "ART-20260804-000101"
CANONICAL_ARTIFACT_ID = "ART-20260804-000102"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def cleared_for(
    content: bytes,
    filename: str,
    *,
    force_allow: bool = False,
) -> SecurityClearedArtifact:
    artifact = ArtifactReference(
        artifact_id=RAW_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref=f"package/{filename}",
        content_hash=sha256(content).hexdigest(),
    )
    if force_allow:
        result = SecurityResult(
            bid_id=BID_ID,
            document_id=DOCUMENT_ID,
            artifact=artifact,
            content_hash=artifact.content_hash,
            verdict=SecurityVerdict.ALLOW,
            scanner="synthetic-test-gate",
            scanner_version="1.0.0",
            policy_version="synthetic-test-gate:0.0.0",
            decided_at=NOW,
        )
    else:
        assessment = DeterministicPreflightScanner().assess(
            artifact=artifact,
            document_id=DOCUMENT_ID,
            filename=Path(filename).name,
            content=content,
            assessed_at=NOW,
        )
        result = decide_document(assessment)
        assert result.verdict is SecurityVerdict.ALLOW, "fixture must clear the real gate"
    return SecurityClearedArtifact(
        artifact=artifact,
        document_id=DOCUMENT_ID,
        security_result=result,
    )


def canonical_for(
    parser: DocumentParser,
    content: bytes,
    filename: str,
    *,
    force_allow: bool = False,
) -> tuple[CanonicalDocument, ParsedContent]:
    cleared = cleared_for(content, filename, force_allow=force_allow)
    parsed = parser.parse(
        cleared=cleared,
        content=content,
        filename=filename,
        canonical_artifact_id=CANONICAL_ARTIFACT_ID,
    )
    document = build_canonical_document(
        cleared,
        parsed,
        filename=filename,
        canonical_artifact_id=CANONICAL_ARTIFACT_ID,
        run_id=RUN_ID,
        created_at=NOW,
        parser_name=parser.parser_name,
        parser_version=parser.parser_version,
    )
    return document, parsed


def find_cell(document: CanonicalDocument, cell_id: str) -> TableCell:
    for page in document.pages:
        for table in page.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.cell_id == cell_id:
                        return cell
    msg = f"cell {cell_id} not found"
    raise AssertionError(msg)


def test_plain_text_parser_builds_line_paragraph_provenance() -> None:
    content = (FIXTURES / "rfp-minimal" / "notes.txt").read_bytes()

    document, parsed = canonical_for(PlainTextParser(), content, "notes.txt")

    assert parsed.warnings == ()
    assert len(document.pages) == 1
    paragraphs = document.pages[0].paragraphs
    assert paragraphs[1].text == "REQ-T1: The supplier MUST name a single point of contact."
    assert paragraphs[1].source.locator.page == 1
    assert paragraphs[1].source.locator.paragraph_id == paragraphs[1].paragraph_id
    assert paragraphs[1].source.canonical_artifact_id == CANONICAL_ARTIFACT_ID
    assert document.metadata.page_count == 1


def test_plain_text_parser_rejects_empty_and_non_utf8_content() -> None:
    with pytest.raises(UnsupportedDocumentError, match="no extractable text"):
        canonical_for(PlainTextParser(), b"   \n\t\n", "empty.txt", force_allow=True)
    with pytest.raises(DocumentParsingError, match="not valid UTF-8"):
        canonical_for(PlainTextParser(), b"\x80broken", "broken.txt", force_allow=True)


def test_parsers_fail_closed_on_cleared_content_mismatch() -> None:
    cleared = cleared_for(b"original text", "notes.txt")

    with pytest.raises(ClearedContentMismatchError):
        PlainTextParser().parse(
            cleared=cleared,
            content=b"tampered text",
            filename="notes.txt",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
        )


def test_pdf_parser_extracts_two_pages_with_correct_page_provenance() -> None:
    content = (FIXTURES / "rfp-minimal" / "rfp-invitation.pdf").read_bytes()

    document, parsed = canonical_for(PdfTextParser(), content, "rfp-invitation.pdf")

    assert parsed.warnings == ()
    assert document.metadata.title == "Synthetic RFP BF-2026-DEMO - Invitation to Tender"
    assert document.metadata.page_count == 2
    page_1, page_2 = document.pages
    deadline_line = next(
        paragraph
        for paragraph in page_1.paragraphs
        if paragraph.text.startswith("Submission deadline")
    )
    requirement_line = next(
        paragraph for paragraph in page_2.paragraphs if paragraph.text.startswith("REQ-P2")
    )
    assert deadline_line.source.locator.page == 1
    assert requirement_line.source.locator.page == 2
    assert requirement_line.source.quote == requirement_line.text
    assert requirement_line.source.document_hash == sha256(content).hexdigest()


def test_pdf_parser_reports_textless_pdfs_as_unsupported() -> None:
    content = (FIXTURES / "rfp-unsupported" / "blank-scan.pdf").read_bytes()

    with pytest.raises(UnsupportedDocumentError, match="no extractable text"):
        canonical_for(PdfTextParser(), content, "blank-scan.pdf")


def test_pdf_parser_never_succeeds_on_encrypted_or_corrupt_input() -> None:
    encrypted = (FIXTURES / "rfp-review" / "declared-encrypted.pdf").read_bytes()
    corrupt = b"%PDF-1.4\nnonsense without structure\n%%EOF\n"

    with pytest.raises(ParserError):
        canonical_for(PdfTextParser(), encrypted, "declared-encrypted.pdf", force_allow=True)
    with pytest.raises(ParserError):
        canonical_for(PdfTextParser(), corrupt, "corrupt.pdf", force_allow=True)


def test_xlsx_parser_maps_sheets_to_pages_with_cell_provenance() -> None:
    content = (FIXTURES / "rfp-minimal" / "requirements-matrix.xlsx").read_bytes()

    document, parsed = canonical_for(XlsxTableParser(), content, "requirements-matrix.xlsx")

    assert document.metadata.page_count == 3
    assert [page.tables[0].caption for page in document.pages] == [
        "Requirements",
        "Timeline",
        "Formalities",
    ]
    cell = find_cell(document, "Requirements!B2")
    assert cell.text == "The supplier MUST provide a German-speaking service desk."
    assert cell.row == 2
    assert cell.column == 2
    assert cell.source.locator.page == 1
    assert cell.source.locator.cell_id == "Requirements!B2"
    assert cell.source.canonical_artifact_id == CANONICAL_ARTIFACT_ID
    assert parsed.warnings == ()


def test_xlsx_parser_reports_formulas_without_cached_values() -> None:
    content = (FIXTURES / "rfp-quality-review" / "quality-matrix.xlsx").read_bytes()

    _, parsed = canonical_for(XlsxTableParser(), content, "quality-matrix.xlsx")

    assert any("Calc!C1" in warning for warning in parsed.warnings)


def test_xlsx_parser_fails_closed_on_corrupt_workbooks() -> None:
    with pytest.raises(DocumentParsingError, match="could not be read"):
        canonical_for(
            XlsxTableParser(),
            b"PK\x03\x04 not a workbook",
            "broken.xlsx",
            force_allow=True,
        )


def test_registry_supports_exactly_the_mvp_types() -> None:
    assert isinstance(parser_for("pdf"), PdfTextParser)
    assert isinstance(parser_for("xlsx"), XlsxTableParser)
    assert isinstance(parser_for("txt"), PlainTextParser)
    assert isinstance(parser_for("csv"), PlainTextParser)
    assert parser_for("docx") is None
    assert parser_for("png") is None
