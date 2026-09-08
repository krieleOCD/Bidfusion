"""Line-oriented plain-text parser for TXT and CSV documents."""

from __future__ import annotations

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


class PlainTextParser:
    """Turn UTF-8 text into one canonical page of line paragraphs."""

    parser_name = "bidfusion-plain-text-parser"
    parser_version = "0.1.0"

    def parse(
        self,
        *,
        cleared: SecurityClearedArtifact,
        content: bytes,
        filename: str,
        canonical_artifact_id: ArtifactId,
    ) -> ParsedContent:
        """Parse cleared text bytes; empty documents are explicitly unsupported."""
        verify_cleared_content(cleared, content)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as failure:
            msg = "text document is not valid UTF-8"
            raise DocumentParsingError(msg) from failure

        lines = [line.strip() for line in text.splitlines()]
        paragraphs = tuple(
            Paragraph(
                paragraph_id=f"para-1-{order:03d}",
                text=line,
                order=order,
                source=block_source(
                    cleared,
                    filename=filename,
                    canonical_artifact_id=canonical_artifact_id,
                    locator=SourceLocator(page=1, paragraph_id=f"para-1-{order:03d}"),
                    quote=line,
                ),
            )
            for order, line in enumerate(
                (line for line in lines if line),
                start=1,
            )
        )
        if not paragraphs:
            msg = "text document contains no extractable text"
            raise UnsupportedDocumentError(msg)

        return ParsedContent(pages=(Page(page_number=1, paragraphs=paragraphs),))
