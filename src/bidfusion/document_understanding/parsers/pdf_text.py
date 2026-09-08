"""Text extraction for text-based (non-scanned) PDF documents via pypdf.

Deliberately out of scope: OCR, scanned pages, layout understanding, and
image or diagram interpretation. Encrypted, corrupt, and practically
textless PDFs are reported as unsupported or parsing failures — never as a
successful extraction.
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from bidfusion.document_understanding.canonical import (
    DocumentParsingError,
    ParsedContent,
    UnsupportedDocumentError,
    block_source,
    verify_cleared_content,
)
from bidfusion.schemas.document import Page, Paragraph
from bidfusion.schemas.ids import ArtifactId
from bidfusion.schemas.provenance import SourceLocator
from bidfusion.schemas.security import SecurityClearedArtifact


class PdfTextParser:
    """Extract per-page text lines from a text-based PDF."""

    parser_name = "bidfusion-pdf-text-parser"
    parser_version = "0.1.0"

    def parse(
        self,
        *,
        cleared: SecurityClearedArtifact,
        content: bytes,
        filename: str,
        canonical_artifact_id: ArtifactId,
    ) -> ParsedContent:
        """Parse cleared PDF bytes into provenance-bound page paragraphs."""
        verify_cleared_content(cleared, content)
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                msg = "encrypted PDFs are not supported by the MVP parser"
                raise UnsupportedDocumentError(msg)
            page_texts = [page.extract_text() or "" for page in reader.pages]
        except UnsupportedDocumentError:
            raise
        except Exception as failure:
            msg = "PDF could not be parsed as a text-based document"
            raise DocumentParsingError(msg) from failure

        pages: list[Page] = []
        warnings: list[str] = []
        total_paragraphs = 0
        for page_number, text in enumerate(page_texts, start=1):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            paragraphs = tuple(
                Paragraph(
                    paragraph_id=f"para-{page_number}-{order:03d}",
                    text=line,
                    order=order,
                    source=block_source(
                        cleared,
                        filename=filename,
                        canonical_artifact_id=canonical_artifact_id,
                        locator=SourceLocator(
                            page=page_number,
                            paragraph_id=f"para-{page_number}-{order:03d}",
                        ),
                        quote=line,
                    ),
                )
                for order, line in enumerate(lines, start=1)
            )
            if not paragraphs:
                warnings.append(f"page {page_number} contains no extractable text")
            total_paragraphs += len(paragraphs)
            pages.append(Page(page_number=page_number, paragraphs=paragraphs))

        if total_paragraphs == 0:
            msg = "PDF contains no extractable text (scanned or empty documents need OCR)"
            raise UnsupportedDocumentError(msg)

        title = pages[0].paragraphs[0].text if pages[0].paragraphs else None
        return ParsedContent(pages=tuple(pages), title=title, warnings=tuple(warnings))
