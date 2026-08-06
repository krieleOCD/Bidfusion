"""Deterministic DOCX text and table extraction from ``word/document.xml``.

Standard library only — ``zipfile`` plus ``xml.etree.ElementTree``. No
Office library is involved, nothing is written to disk, and no archive
entry other than the main document part is ever decompressed.

Hardening. These bytes already cleared the Security Gate, but a cleared
archive is still attacker-shaped input, so every structural property the
parser relies on is re-checked here and fails closed:

- **Duplicate entry names are refused.** :func:`~bidfusion.shared.filetype.
  inspect_archive` — and therefore the Security Gate — reduces entry names
  to a ``frozenset``, while :meth:`zipfile.ZipFile.read` returns the *last*
  matching entry. An archive carrying two ``word/document.xml`` members
  could otherwise have one payload scanned and a different one parsed.
- **Unsafe entry names are refused** (absolute, drive-qualified,
  backslash-separated, or containing a ``..`` component) even though this
  parser never extracts anything to disk.
- **Encrypted entries, excessive entry counts, oversized declared
  expansion, and bomb-like compression ratios are refused** before any
  decompression happens.
- **The main document part is read through a hard byte ceiling** instead
  of trusting the size the archive declares for it.
- **A document type declaration is refused outright.**
  ``xml.etree.ElementTree`` *does* expand internal entities, so a
  billion-laughs payload is a real risk; legitimate OOXML never carries a
  ``<!DOCTYPE``. External entities are separately refused by the stdlib
  parser, which resolves no external references.
- **A VBA macro project makes the document unsupported.** The Security
  Gate already blocks macro-enabled Office files at CRITICAL severity, so
  this is defense in depth for callers that bypass the pipeline. The entry
  suffix comes from :mod:`bidfusion.shared.filetype` so macro presence
  stays defined in exactly one place.

Content model. A DOCX has no page structure until it is laid out, so every
block lands on canonical page 1 rather than inventing page numbers that
provenance could not defend. Locators keep the source positions instead:
``paragraph_id`` carries the 1-based index of the paragraph within
``w:body`` — stable even when blank paragraphs are dropped — tables carry
their own body index, and cells carry row and column. Headings become
``Section`` nodes *and* stay in the paragraph stream, so structure is
captured without removing heading text from what downstream extraction
reads. Only ``w:t`` contributes text: field codes (``w:instrText``) and
tracked deletions (``w:delText``) are deliberately ignored.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from io import BytesIO
from xml.etree import ElementTree

from bidfusion.document_understanding.canonical import (
    DocumentParsingError,
    ParsedContent,
    UnsupportedDocumentError,
    block_source,
    verify_cleared_content,
)
from bidfusion.schemas.document import Page, Paragraph, Section, Table, TableCell, TableRow
from bidfusion.schemas.ids import ArtifactId
from bidfusion.schemas.provenance import SourceLocator, SourceReference
from bidfusion.schemas.security import SecurityClearedArtifact
from bidfusion.shared.filetype import MACRO_PROJECT_ENTRY_SUFFIX

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_WORD_NAMESPACE}}}"
_MAIN_DOCUMENT_PART = "word/document.xml"

#: The single canonical page every DOCX block is bound to.
_PAGE_NUMBER = 1

#: Entry-count ceiling, mirroring the deterministic preflight limit.
MAX_ARCHIVE_ENTRIES = 10_000

#: Declared whole-archive expansion ceiling, mirroring preflight.
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

#: Whole-archive compression-ratio ceiling, mirroring preflight.
MAX_COMPRESSION_RATIO = 200.0

#: Hard ceiling on the main document part, enforced against both the
#: declared size and the bytes actually produced while reading.
MAX_DOCUMENT_PART_BYTES = 64 * 1024 * 1024

_READ_CHUNK_BYTES = 1024 * 1024

_DOCTYPE_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)")
_HEADING_STYLE = re.compile(r"^heading([1-9])$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")

#: Builds one canonical-bound provenance reference for a block or cell.
_SourceFactory = Callable[[SourceLocator, str | None], SourceReference]


class DocxTextParser:
    """Extract paragraphs, headings, and tables from a WordprocessingML document."""

    parser_name = "bidfusion-docx-text-parser"
    parser_version = "0.1.0"

    def parse(
        self,
        *,
        cleared: SecurityClearedArtifact,
        content: bytes,
        filename: str,
        canonical_artifact_id: ArtifactId,
    ) -> ParsedContent:
        """Parse cleared DOCX bytes into one canonical page of blocks."""
        verify_cleared_content(cleared, content)
        body = _read_body(content)

        def source(locator: SourceLocator, quote: str | None = None) -> SourceReference:
            return block_source(
                cleared,
                filename=filename,
                canonical_artifact_id=canonical_artifact_id,
                locator=locator,
                quote=quote,
            )

        paragraphs: list[Paragraph] = []
        sections: list[Section] = []
        tables: list[Table] = []
        warnings: list[str] = []
        open_sections: list[tuple[int, str]] = []
        current_section_id: str | None = None
        title: str | None = None
        paragraph_index = 0
        table_index = 0

        for element in body:
            if element.tag == f"{_W}p":
                paragraph_index += 1
                text = _element_text(element)
                if not text:
                    continue

                level = _heading_level(element)
                if level is not None:
                    section_id = f"section-1-{paragraph_index:03d}"
                    while open_sections and open_sections[-1][0] >= level:
                        open_sections.pop()
                    parent_section_id = open_sections[-1][1] if open_sections else None
                    sections.append(
                        Section(
                            section_id=section_id,
                            title=text,
                            level=level,
                            order=len(sections),
                            parent_section_id=parent_section_id,
                            source=source(
                                SourceLocator(page=_PAGE_NUMBER, section_id=section_id),
                                text,
                            ),
                        )
                    )
                    open_sections.append((level, section_id))
                    current_section_id = section_id
                    if title is None:
                        title = text

                paragraph_id = f"para-1-{paragraph_index:03d}"
                paragraphs.append(
                    Paragraph(
                        paragraph_id=paragraph_id,
                        text=text,
                        order=len(paragraphs),
                        section_id=current_section_id,
                        source=source(
                            SourceLocator(page=_PAGE_NUMBER, paragraph_id=paragraph_id),
                            text,
                        ),
                    )
                )
            elif element.tag == f"{_W}tbl":
                table_index += 1
                table_id = f"table-1-{table_index:03d}"
                rows, nested = _table_rows(element, table_id=table_id, make_source=source)
                if nested:
                    warnings.append(
                        f"nested table content in {table_id} was flattened into its parent cells"
                    )
                if not rows:
                    warnings.append(f"{table_id} contains no readable cells")
                    continue
                tables.append(
                    Table(
                        table_id=table_id,
                        order=table_index - 1,
                        section_id=current_section_id,
                        rows=rows,
                        source=source(SourceLocator(page=_PAGE_NUMBER, table_id=table_id)),
                    )
                )

        has_text = any(item.text for item in paragraphs) or any(
            cell.text for table in tables for row in table.rows for cell in row.cells
        )
        if not has_text:
            msg = "DOCX document contains no extractable text"
            raise UnsupportedDocumentError(msg)

        page = Page(
            page_number=_PAGE_NUMBER,
            sections=tuple(sections),
            paragraphs=tuple(paragraphs),
            tables=tuple(tables),
        )
        return ParsedContent(pages=(page,), title=title, warnings=tuple(warnings))


def _read_body(content: bytes) -> ElementTree.Element:
    """Return the validated ``w:body`` element of the main document part."""
    document_xml = _read_document_part(content)
    if _DOCTYPE_DECLARATION.search(document_xml):
        msg = "DOCX main document part carries a document type declaration"
        raise DocumentParsingError(msg)
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as failure:
        msg = "DOCX main document part could not be parsed"
        raise DocumentParsingError(msg) from failure

    body = root.find(f"{_W}body")
    if body is None:
        msg = "DOCX main document part has no document body"
        raise UnsupportedDocumentError(msg)
    return body


def _read_document_part(content: bytes) -> bytes:
    """Validate the archive structure and read only the main document part."""
    try:
        archive = zipfile.ZipFile(BytesIO(content), "r")
    except (OSError, ValueError, zipfile.BadZipFile) as failure:
        msg = "DOCX archive could not be read"
        raise DocumentParsingError(msg) from failure

    with archive:
        entries = archive.infolist()
        _validate_archive(entries)
        document_entry = next(
            (entry for entry in entries if entry.filename.lower() == _MAIN_DOCUMENT_PART),
            None,
        )
        if document_entry is None:
            msg = "DOCX archive has no main document part"
            raise DocumentParsingError(msg)
        return _read_bounded_entry(archive, document_entry)


def _validate_archive(entries: list[zipfile.ZipInfo]) -> None:
    """Refuse every archive shape this parser is not willing to reason about."""
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        msg = "DOCX archive exceeds the supported entry-count limit"
        raise DocumentParsingError(msg)

    names = [entry.filename.lower() for entry in entries]
    if len(set(names)) != len(names):
        msg = "DOCX archive contains a duplicate entry name"
        raise DocumentParsingError(msg)

    for entry in entries:
        if _is_unsafe_entry_name(entry.filename):
            msg = "DOCX archive contains an unsafe entry name"
            raise DocumentParsingError(msg)
        if entry.flag_bits & 0x1:
            msg = "DOCX archive contains encrypted entries"
            raise DocumentParsingError(msg)

    if any(name.endswith(MACRO_PROJECT_ENTRY_SUFFIX) for name in names):
        msg = "DOCX document contains a VBA macro project"
        raise UnsupportedDocumentError(msg)

    uncompressed = sum(entry.file_size for entry in entries)
    compressed = sum(entry.compress_size for entry in entries)
    ratio = uncompressed / max(compressed, 1)
    if uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES or ratio > MAX_COMPRESSION_RATIO:
        msg = "DOCX archive exceeds the supported expansion limit"
        raise DocumentParsingError(msg)


def _is_unsafe_entry_name(name: str) -> bool:
    """Whether an archive entry name escapes, or could escape, its container."""
    if not name or name.startswith("/") or "\\" in name:
        return True
    if _WINDOWS_DRIVE.match(name):
        return True
    return any(part == ".." for part in name.split("/"))


def _read_bounded_entry(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> bytes:
    """Read one entry under a hard ceiling, never trusting its declared size."""
    if entry.file_size > MAX_DOCUMENT_PART_BYTES:
        msg = "DOCX main document part exceeds the supported expansion limit"
        raise DocumentParsingError(msg)

    chunks: list[bytes] = []
    total = 0
    try:
        with archive.open(entry, "r") as stream:
            while chunk := stream.read(_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_DOCUMENT_PART_BYTES:
                    msg = "DOCX main document part exceeds the supported expansion limit"
                    raise DocumentParsingError(msg)
                chunks.append(chunk)
    except (OSError, ValueError, zipfile.BadZipFile) as failure:
        msg = "DOCX main document part could not be read"
        raise DocumentParsingError(msg) from failure
    return b"".join(chunks)


def _table_rows(
    element: ElementTree.Element,
    *,
    table_id: str,
    make_source: _SourceFactory,
) -> tuple[tuple[TableRow, ...], bool]:
    """Build canonical rows from direct ``w:tr`` children, preserving order.

    Only direct children are walked, so a nested table never contributes
    phantom top-level rows; its text is flattened into the enclosing cell
    and reported through the returned ``nested`` flag instead.
    """
    rows: list[TableRow] = []
    nested = False
    for row_number, row_element in enumerate(element.findall(f"{_W}tr"), start=1):
        cells: list[TableCell] = []
        column = 1
        for cell_element in row_element.findall(f"{_W}tc"):
            if cell_element.find(f".//{_W}tbl") is not None:
                nested = True
            text = _cell_text(cell_element)
            span = _grid_span(cell_element)
            cell_id = f"{table_id}-r{row_number}c{column}"
            cells.append(
                TableCell(
                    cell_id=cell_id,
                    text=text,
                    row=row_number,
                    column=column,
                    column_span=span,
                    source=make_source(
                        SourceLocator(
                            page=_PAGE_NUMBER,
                            table_id=table_id,
                            row=row_number,
                            column=column,
                            cell_id=cell_id,
                        ),
                        text,
                    ),
                )
            )
            column += span
        if cells:
            rows.append(TableRow(row_number=row_number, cells=tuple(cells)))
    return tuple(rows), nested


def _element_text(element: ElementTree.Element) -> str:
    """Concatenate visible run text, honoring tabs and explicit breaks."""
    parts: list[str] = []
    for node in element.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _cell_text(cell: ElementTree.Element) -> str:
    """Join a cell's paragraph texts, including any flattened nested table."""
    texts = [_element_text(paragraph) for paragraph in cell.iter(f"{_W}p")]
    return "\n".join(text for text in texts if text)


def _grid_span(cell: ElementTree.Element) -> int:
    """Horizontal span of a cell; anything unparsable counts as a single column."""
    properties = cell.find(f"{_W}tcPr")
    if properties is None:
        return 1
    span = properties.find(f"{_W}gridSpan")
    if span is None:
        return 1
    raw = span.get(f"{_W}val")
    if raw is None or not raw.isdigit():
        return 1
    return max(int(raw), 1)


def _heading_level(paragraph: ElementTree.Element) -> int | None:
    """Heading level from a ``Heading N`` style or an outline level, else ``None``."""
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return None

    style = properties.find(f"{_W}pStyle")
    if style is not None:
        raw = (style.get(f"{_W}val") or "").replace(" ", "").replace("-", "").lower()
        match = _HEADING_STYLE.match(raw)
        if match:
            return int(match.group(1))

    outline = properties.find(f"{_W}outlineLvl")
    if outline is not None:
        raw_level = outline.get(f"{_W}val")
        if raw_level is not None and raw_level.isdigit():
            level = int(raw_level) + 1
            if 1 <= level <= 9:
                return level
    return None
