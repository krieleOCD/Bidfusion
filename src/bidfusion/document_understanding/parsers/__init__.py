"""Format parsers: PDF, DOCX, spreadsheets, CSV, PowerPoint.

The MVP slice implements text-based PDF, regular XLSX, and plain
TXT/CSV parsing. Every other registered type is explicitly unsupported
and must be routed to review instead of being silently skipped.
"""

from bidfusion.document_understanding.canonical import DocumentParser
from bidfusion.document_understanding.parsers.pdf_text import PdfTextParser
from bidfusion.document_understanding.parsers.plain_text import PlainTextParser
from bidfusion.document_understanding.parsers.xlsx_table import XlsxTableParser

_PARSERS_BY_FILE_TYPE: dict[str, DocumentParser] = {
    "pdf": PdfTextParser(),
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
    "PdfTextParser",
    "PlainTextParser",
    "XlsxTableParser",
    "parser_for",
]
