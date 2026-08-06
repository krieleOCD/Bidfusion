"""Tests for the deterministic DOCX text parser and its ZIP/XML hardening.

Every DOCX in this module is built in-process from synthetic bytes. The
adversarial archives (traversal entries, decompression bombs, entity
bombs, macro projects) are deliberately *not* committed under
``fixtures/synthetic/``: that directory is a trusted input root
(:func:`bidfusion.shared.pathguards.trusted_synthetic_root`) and hostile
archives have no place in it.
"""

from __future__ import annotations

import warnings
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest

from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY
from bidfusion.document_understanding.canonical import (
    ClearedContentMismatchError,
    DocumentParsingError,
    ParsedContent,
    UnsupportedDocumentError,
    build_canonical_document,
)
from bidfusion.document_understanding.parsers import DocxTextParser, parser_for
from bidfusion.document_understanding.parsers.docx_text import MAX_DOCUMENT_PART_BYTES
from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    SecurityClearedArtifact,
    SecurityResult,
    SecurityVerdict,
)
from bidfusion.security import DeterministicPreflightScanner, decide_document

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
DOCUMENT_ID = "DOC-001"
RAW_ARTIFACT_ID = "ART-20260804-000101"
CANONICAL_ARTIFACT_ID = "ART-20260804-000102"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 12, 0, 0)

CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="xml" ContentType="application/xml"/>'
    b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    b'officedocument.wordprocessingml.document.main+xml"/>'
    b"</Types>"
)


# --------------------------------------------------------------------------
# Synthetic DOCX builders
# --------------------------------------------------------------------------


def document_xml(body: str) -> bytes:
    """Wrap WordprocessingML body markup in a minimal document part."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    ).encode()


def paragraph(text: str, *, style: str | None = None, outline_level: int | None = None) -> str:
    """One ``w:p`` element, optionally carrying heading properties."""
    properties = ""
    if style is not None:
        properties += f'<w:pStyle w:val="{style}"/>'
    if outline_level is not None:
        properties += f'<w:outlineLvl w:val="{outline_level}"/>'
    prefix = f"<w:pPr>{properties}</w:pPr>" if properties else ""
    return f"<w:p>{prefix}<w:r><w:t>{text}</w:t></w:r></w:p>"


def table(rows: list[list[str]], *, spans: dict[tuple[int, int], int] | None = None) -> str:
    """One ``w:tbl`` element from row-major cell texts."""
    spans = spans or {}
    markup = "<w:tbl>"
    for row_index, row in enumerate(rows, start=1):
        markup += "<w:tr>"
        for column_index, cell in enumerate(row, start=1):
            span = spans.get((row_index, column_index))
            properties = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span else ""
            markup += f"<w:tc>{properties}<w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>"
        markup += "</w:tr>"
    return markup + "</w:tbl>"


def docx_bytes(
    entries: Mapping[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """Build a deterministic DOCX-shaped archive from exact entry bytes."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = compression
            archive.writestr(info, payload)
    return buffer.getvalue()


def simple_docx(body: str, *, extra: Mapping[str, bytes] | None = None) -> bytes:
    """A well-formed synthetic DOCX carrying the given body markup."""
    entries: dict[str, bytes] = {
        "[Content_Types].xml": CONTENT_TYPES_XML,
        "word/document.xml": document_xml(body),
    }
    entries.update(extra or {})
    return docx_bytes(entries)


# --------------------------------------------------------------------------
# Gate and canonical helpers
# --------------------------------------------------------------------------


def cleared_for(
    content: bytes, filename: str, *, force_allow: bool = False
) -> SecurityClearedArtifact:
    """Clear bytes through the real preflight and gate policy unless forced."""
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
            filename=filename,
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


def parse(
    content: bytes, filename: str = "service-description.docx", *, force_allow: bool = False
) -> ParsedContent:
    """Parse synthetic DOCX bytes with the real parser."""
    cleared = cleared_for(content, filename, force_allow=force_allow)
    return DocxTextParser().parse(
        cleared=cleared,
        content=content,
        filename=filename,
        canonical_artifact_id=CANONICAL_ARTIFACT_ID,
    )


def canonical_for(
    content: bytes,
    filename: str = "service-description.docx",
    *,
    force_allow: bool = False,
) -> tuple[CanonicalDocument, ParsedContent]:
    """Parse and assemble the sealed canonical document."""
    cleared = cleared_for(content, filename, force_allow=force_allow)
    parser = DocxTextParser()
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


# --------------------------------------------------------------------------
# Paragraphs
# --------------------------------------------------------------------------


def test_paragraphs_keep_document_order_and_paragraph_index_locators() -> None:
    content = simple_docx(
        paragraph("Managed Threat Detection covers 24x7 monitoring.")
        + paragraph("The service MUST provide a named service delivery manager.")
        + paragraph("Out of scope: on-premise hardware replacement.")
    )

    document, parsed = canonical_for(content)

    assert parsed.warnings == ()
    assert len(document.pages) == 1
    paragraphs = document.pages[0].paragraphs
    assert [item.text for item in paragraphs] == [
        "Managed Threat Detection covers 24x7 monitoring.",
        "The service MUST provide a named service delivery manager.",
        "Out of scope: on-premise hardware replacement.",
    ]
    assert [item.order for item in paragraphs] == [0, 1, 2]
    assert [item.paragraph_id for item in paragraphs] == [
        "para-1-001",
        "para-1-002",
        "para-1-003",
    ]
    for item in paragraphs:
        assert item.source.locator.page == 1
        assert item.source.locator.paragraph_id == item.paragraph_id
        assert item.source.canonical_artifact_id == CANONICAL_ARTIFACT_ID
        assert item.source.quote == item.text
        assert item.source.document_hash == sha256(content).hexdigest()


def test_paragraph_ids_preserve_the_source_index_across_skipped_empty_paragraphs() -> None:
    content = simple_docx(
        paragraph("First clause.")
        + "<w:p/>"
        + "<w:p><w:r><w:t>   </w:t></w:r></w:p>"
        + paragraph("Fourth clause.")
    )

    parsed = parse(content)

    paragraphs = parsed.pages[0].paragraphs
    assert [item.text for item in paragraphs] == ["First clause.", "Fourth clause."]
    # Emission order is dense; the locator still points at the true source index.
    assert [item.order for item in paragraphs] == [0, 1]
    assert [item.paragraph_id for item in paragraphs] == ["para-1-001", "para-1-004"]


def test_runs_tabs_and_breaks_join_into_one_paragraph_text() -> None:
    content = simple_docx(
        "<w:p><w:r><w:t>Availability</w:t></w:r><w:r><w:tab/><w:t>99.5%</w:t></w:r>"
        "<w:r><w:br/><w:t>Measured monthly.</w:t></w:r></w:p>"
    )

    parsed = parse(content)

    assert parsed.pages[0].paragraphs[0].text == "Availability\t99.5%\nMeasured monthly."


def test_field_codes_and_tracked_deletions_are_never_emitted_as_text() -> None:
    content = simple_docx(
        "<w:p><w:r><w:t>Retention period is </w:t></w:r>"
        "<w:r><w:instrText> REF _Ref12345 \\h </w:instrText></w:r>"
        "<w:del><w:r><w:delText>thirty</w:delText></w:r></w:del>"
        "<w:r><w:t>ninety days.</w:t></w:r></w:p>"
    )

    parsed = parse(content)

    text = parsed.pages[0].paragraphs[0].text
    assert text == "Retention period is ninety days."
    assert "thirty" not in text
    assert "REF _Ref12345" not in text


# --------------------------------------------------------------------------
# Headings
# --------------------------------------------------------------------------


def test_headings_become_sections_with_levels_and_parents() -> None:
    content = simple_docx(
        paragraph("Service Description", style="Heading1")
        + paragraph("Scope of the managed service.")
        + paragraph("Exclusions", style="Heading2")
        + paragraph("Hardware replacement is excluded.")
        + paragraph("Annexes", style="Heading1")
    )

    document, _ = canonical_for(content)

    sections = document.pages[0].sections
    assert [section.title for section in sections] == [
        "Service Description",
        "Exclusions",
        "Annexes",
    ]
    assert [section.level for section in sections] == [1, 2, 1]
    assert sections[0].parent_section_id is None
    assert sections[1].parent_section_id == sections[0].section_id
    assert sections[2].parent_section_id is None
    assert [section.order for section in sections] == [0, 1, 2]
    for section in sections:
        assert section.source.locator.page == 1
        assert section.source.locator.section_id == section.section_id


def test_heading_text_is_also_kept_as_a_paragraph_so_no_content_is_lost() -> None:
    content = simple_docx(
        paragraph("Exclusions", style="Heading1") + paragraph("Hardware replacement is excluded.")
    )

    document, _ = canonical_for(content)

    page = document.pages[0]
    assert [item.text for item in page.paragraphs] == [
        "Exclusions",
        "Hardware replacement is excluded.",
    ]
    heading_section = page.sections[0]
    assert all(item.section_id == heading_section.section_id for item in page.paragraphs)


def test_outline_level_marks_a_heading_without_a_heading_style() -> None:
    content = simple_docx(
        paragraph("Responsibilities", outline_level=0) + paragraph("Customer provides log access.")
    )

    document, _ = canonical_for(content)

    sections = document.pages[0].sections
    assert [section.title for section in sections] == ["Responsibilities"]
    assert sections[0].level == 1


def test_document_title_comes_from_the_first_heading() -> None:
    content = simple_docx(
        paragraph("Managed Threat Detection", style="Heading1") + paragraph("Body text.")
    )

    document, _ = canonical_for(content)

    assert document.metadata.title == "Managed Threat Detection"


def test_documents_without_headings_have_no_title_and_no_sections() -> None:
    content = simple_docx(paragraph("Body text only."))

    document, _ = canonical_for(content)

    assert document.metadata.title is None
    assert document.pages[0].sections == ()
    assert document.pages[0].paragraphs[0].section_id is None


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def test_tables_preserve_row_and_column_order_with_cell_locators() -> None:
    content = simple_docx(
        table(
            [
                ["Metric", "Target", "Measurement"],
                ["Time to detect", "15 minutes", "Monthly average"],
                ["Time to respond", "30 minutes", "Monthly average"],
            ]
        )
    )

    document, parsed = canonical_for(content)

    assert parsed.warnings == ()
    tables = document.pages[0].tables
    assert len(tables) == 1
    assert tables[0].table_id == "table-1-001"
    assert tables[0].order == 0
    assert [row.row_number for row in tables[0].rows] == [1, 2, 3]
    assert [cell.text for cell in tables[0].rows[0].cells] == ["Metric", "Target", "Measurement"]
    assert [cell.column for cell in tables[0].rows[0].cells] == [1, 2, 3]

    cell = tables[0].rows[1].cells[1]
    assert cell.text == "15 minutes"
    assert cell.row == 2
    assert cell.column == 2
    assert cell.cell_id == "table-1-001-r2c2"
    assert cell.source.locator.page == 1
    assert cell.source.locator.table_id == "table-1-001"
    assert cell.source.locator.row == 2
    assert cell.source.locator.column == 2
    assert cell.source.locator.cell_id == cell.cell_id


def test_multiple_tables_are_indexed_in_document_order() -> None:
    content = simple_docx(table([["A"]]) + paragraph("Between the tables.") + table([["B"], ["C"]]))

    document, _ = canonical_for(content)

    tables = document.pages[0].tables
    assert [item.table_id for item in tables] == ["table-1-001", "table-1-002"]
    assert [item.order for item in tables] == [0, 1]
    assert [len(item.rows) for item in tables] == [1, 2]


def test_grid_span_widens_a_cell_and_advances_the_column_index() -> None:
    content = simple_docx(
        table([["Header spanning two", "Third"], ["One", "Two", "Three"]], spans={(1, 1): 2})
    )

    parsed = parse(content)

    first_row = parsed.pages[0].tables[0].rows[0]
    assert [cell.column for cell in first_row.cells] == [1, 3]
    assert first_row.cells[0].column_span == 2
    assert first_row.cells[1].column_span == 1


def test_empty_table_cells_are_kept_so_column_positions_stay_truthful() -> None:
    content = simple_docx(table([["Filled", "", "Also filled"]]))

    parsed = parse(content)

    cells = parsed.pages[0].tables[0].rows[0].cells
    assert [cell.text for cell in cells] == ["Filled", "", "Also filled"]
    assert [cell.column for cell in cells] == [1, 2, 3]


def test_nested_tables_are_flattened_into_the_cell_text_with_a_warning() -> None:
    inner = table([["Nested value"]])
    content = simple_docx(
        f"<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Outer</w:t></w:r></w:p>{inner}</w:tc></w:tr></w:tbl>"
    )

    parsed = parse(content)

    cell = parsed.pages[0].tables[0].rows[0].cells[0]
    assert "Outer" in cell.text
    assert "Nested value" in cell.text
    assert any("nested table" in warning for warning in parsed.warnings)


# --------------------------------------------------------------------------
# Empty and malformed input
# --------------------------------------------------------------------------


def test_document_without_extractable_text_is_unsupported() -> None:
    content = simple_docx("")

    with pytest.raises(UnsupportedDocumentError, match="no extractable text"):
        parse(content, force_allow=True)


def test_whitespace_only_document_is_unsupported() -> None:
    content = simple_docx("<w:p><w:r><w:t>   </w:t></w:r></w:p>")

    with pytest.raises(UnsupportedDocumentError, match="no extractable text"):
        parse(content, force_allow=True)


def test_malformed_zip_fails_closed() -> None:
    with pytest.raises(DocumentParsingError, match="could not be read"):
        parse(b"PK\x03\x04 definitely not a real archive", force_allow=True)


def test_missing_word_document_part_fails_closed() -> None:
    content = docx_bytes({"[Content_Types].xml": CONTENT_TYPES_XML, "word/styles.xml": b"<a/>"})

    with pytest.raises(DocumentParsingError, match="main document part"):
        parse(content, force_allow=True)


def test_malformed_document_xml_fails_closed() -> None:
    content = docx_bytes(
        {
            "[Content_Types].xml": CONTENT_TYPES_XML,
            "word/document.xml": b"<w:document><w:body><w:p>unclosed",
        }
    )

    with pytest.raises(DocumentParsingError, match="could not be parsed"):
        parse(content, force_allow=True)


def test_cleared_content_mismatch_fails_closed_before_any_parsing() -> None:
    cleared = cleared_for(simple_docx(paragraph("Original.")), "service-description.docx")

    with pytest.raises(ClearedContentMismatchError):
        DocxTextParser().parse(
            cleared=cleared,
            content=simple_docx(paragraph("Tampered.")),
            filename="service-description.docx",
            canonical_artifact_id=CANONICAL_ARTIFACT_ID,
        )


# --------------------------------------------------------------------------
# ZIP and XML hardening
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile_name",
    [
        "../../../etc/passwd",
        "word/../../escape.xml",
        "/absolute/path.xml",
        "C:\\windows\\system32\\evil.xml",
        "word\\..\\..\\escape.xml",
    ],
)
def test_path_traversal_entries_are_rejected(hostile_name: str) -> None:
    content = simple_docx(paragraph("Benign body."), extra={hostile_name: b"payload"})

    with pytest.raises(DocumentParsingError, match="unsafe entry name"):
        parse(content, force_allow=True)


def test_duplicate_document_parts_are_rejected() -> None:
    # zipfile.read() returns the LAST entry while the Security Gate inspects a
    # set of names — the parser must never resolve that ambiguity silently.
    buffer = BytesIO()
    with warnings.catch_warnings():
        # The duplicate name is the point of this fixture, not an accident.
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for payload in (
                document_xml(paragraph("Scanned.")),
                document_xml(paragraph("Executed.")),
            ):
                info = zipfile.ZipInfo("word/document.xml", date_time=_FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)

    with pytest.raises(DocumentParsingError, match="duplicate entry"):
        parse(buffer.getvalue(), force_allow=True)


def test_decompression_bomb_is_rejected_without_materializing_the_payload() -> None:
    # 8 MiB of zeros deflates to a few kilobytes: a ~1000:1 ratio, far past
    # the limit, while keeping the test itself cheap.
    bomb = simple_docx(
        paragraph("Benign body."),
        extra={"word/media/bomb.bin": b"\x00" * (8 * 1024 * 1024)},
    )

    with pytest.raises(DocumentParsingError, match="expansion limit"):
        parse(bomb, force_allow=True)


def test_oversized_document_part_is_rejected() -> None:
    # Stored (uncompressed) so the ratio guard cannot fire first — this must
    # be caught by the document-part ceiling itself.
    oversized = b"<w:document>" + b"A" * (MAX_DOCUMENT_PART_BYTES + 1)
    content = docx_bytes(
        {"[Content_Types].xml": CONTENT_TYPES_XML, "word/document.xml": oversized},
        compression=zipfile.ZIP_STORED,
    )

    with pytest.raises(DocumentParsingError, match="expansion limit"):
        parse(content, force_allow=True)


def test_entity_expansion_bomb_is_rejected_by_the_dtd_guard() -> None:
    bomb = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE lolz ["
        '<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
        "]>"
        f'<w:document xmlns:w="{WORD_NS}"><w:body><w:p><w:r><w:t>&lol3;</w:t>'
        "</w:r></w:p></w:body></w:document>"
    ).encode()
    content = docx_bytes({"[Content_Types].xml": CONTENT_TYPES_XML, "word/document.xml": bomb})

    with pytest.raises(DocumentParsingError, match="document type declaration"):
        parse(content, force_allow=True)


def test_external_entity_declaration_is_rejected_by_the_dtd_guard() -> None:
    hostile = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body><w:p><w:r><w:t>&x;</w:t>'
        "</w:r></w:p></w:body></w:document>"
    ).encode()
    content = docx_bytes({"[Content_Types].xml": CONTENT_TYPES_XML, "word/document.xml": hostile})

    with pytest.raises(DocumentParsingError, match="document type declaration"):
        parse(content, force_allow=True)


def set_encrypted_flag(raw: bytes) -> bytes:
    """Set the ZIP "entry is encrypted" flag in local and central headers.

    ``ZipFile.writestr`` resets ``flag_bits``, so the bit has to be stamped
    into the serialized headers. ``ZipInfo.flag_bits`` is read from the
    central directory, which is why both are patched.
    """
    patched = bytearray(raw)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = 0
        while (index := patched.find(signature, index)) != -1:
            patched[index + flag_offset] |= 0x01
            index += len(signature)
    return bytes(patched)


def test_encrypted_zip_entries_are_rejected() -> None:
    content = set_encrypted_flag(simple_docx(paragraph("Body.")))
    assert any(entry.flag_bits & 0x1 for entry in zipfile.ZipFile(BytesIO(content)).infolist())

    with pytest.raises(DocumentParsingError, match="encrypted"):
        parse(content, force_allow=True)


def test_macro_project_is_refused_by_the_parser() -> None:
    content = simple_docx(
        paragraph("Body with a macro project attached."),
        extra={"word/vbaProject.bin": b"synthetic-inert-macro-placeholder"},
    )

    with pytest.raises(UnsupportedDocumentError, match="macro"):
        parse(content, force_allow=True)


def test_macro_project_is_already_blocked_by_the_security_gate_before_the_parser() -> None:
    content = simple_docx(
        paragraph("Body with a macro project attached."),
        extra={"word/vbaProject.bin": b"synthetic-inert-macro-placeholder"},
    )
    artifact = ArtifactReference(
        artifact_id=RAW_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref="package/macro.docx",
        content_hash=sha256(content).hexdigest(),
    )
    assessment = DeterministicPreflightScanner().assess(
        artifact=artifact,
        document_id=DOCUMENT_ID,
        filename="macro.docx",
        content=content,
        assessed_at=NOW,
    )

    assert decide_document(assessment).verdict is SecurityVerdict.BLOCK


# --------------------------------------------------------------------------
# Integration with the existing gate, registry, and policies
# --------------------------------------------------------------------------


def test_benign_docx_clears_the_real_preflight_and_gate_policy_unchanged() -> None:
    content = simple_docx(paragraph("Wholly benign synthetic service description."))
    artifact = ArtifactReference(
        artifact_id=RAW_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref="package/service-description.docx",
        content_hash=sha256(content).hexdigest(),
    )

    assessment = DeterministicPreflightScanner().assess(
        artifact=artifact,
        document_id=DOCUMENT_ID,
        filename="service-description.docx",
        content=content,
        assessed_at=NOW,
    )

    assert assessment.completed_successfully
    assert decide_document(assessment).verdict is SecurityVerdict.ALLOW


def test_registry_now_resolves_docx() -> None:
    assert isinstance(parser_for("docx"), DocxTextParser)
    assert isinstance(parser_for("DOCX"), DocxTextParser)
    assert parser_for("pptx") is None


def test_slice_a_does_not_widen_the_customer_upload_allowlist() -> None:
    assert DEFAULT_UPLOAD_POLICY.allowed_extensions == frozenset({"pdf", "xlsx", "txt"})


def test_parsing_is_deterministic_for_identical_bytes() -> None:
    content = simple_docx(
        paragraph("Heading", style="Heading1")
        + paragraph("Clause one.")
        + table([["A", "B"], ["C", "D"]])
    )

    first, _ = canonical_for(content)
    second, _ = canonical_for(content)

    assert first.artifact.content_hash == second.artifact.content_hash
    assert first.model_dump_json() == second.model_dump_json()
