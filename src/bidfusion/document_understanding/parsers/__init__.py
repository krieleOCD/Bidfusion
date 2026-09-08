"""Format parsers: PDF, DOCX, spreadsheets, CSV, PowerPoint.

The MVP slice implements text-based PDF, WordprocessingML DOCX, regular
XLSX, and plain TXT/CSV parsing. Every other registered type is
explicitly unsupported and must be routed to review instead of being
silently skipped.

Registering a parser here decides only what the pipeline *can* read once
the Security Gate has cleared a document. It is not an acceptance
decision: which files a customer may upload at all remains the separate,
narrower allowlist in :mod:`bidfusion.bidrun.policy`.
"""

from bidfusion.document_understanding.canonical import DocumentParser
from bidfusion.document_understanding.parsers.docx_text import DocxTextParser
from bidfusion.document_understanding.parsers.pdf_text import PdfTextParser
from bidfusion.document_understanding.parsers.plain_text import PlainTextParser
from bidfusion.document_understanding.parsers.xlsx_table import XlsxTableParser

_PARSERS_BY_FILE_TYPE: dict[str, DocumentParser] = {
    "pdf": PdfTextParser(),
    "docx": DocxTextParser(),
    "xlsx": XlsxTableParser(),
    "txt": PlainTextParser(),
    "csv": PlainTextParser(),
}

SUPPORTED_FILE_TYPES = frozenset(_PARSERS_BY_FILE_TYPE)


def parser_for(file_type: str) -> DocumentParser | None:
    """Return the MVP parser for a registered file type, if one exists."""
    return _PARSERS_BY_FILE_TYPE.get(file_type.lower())


__all__ = [
    "SUPPORTED_FILE_TYPES",
    "DocxTextParser",
    "PdfTextParser",
    "PlainTextParser",
    "XlsxTableParser",
    "parser_for",
]
