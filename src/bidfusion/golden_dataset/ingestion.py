"""Safe, deterministic ingestion of golden knowledge sources.

Responsibility of :class:`GoldenDatasetIngestionService`, and nothing
more: take one inventoried source plus its exact bytes, re-check them
through the **real** security preflight and gate policy, parse them with
the **existing reviewed parsers**, and normalize the result into a
:class:`~bidfusion.golden_dataset.contracts.KnowledgeDocument`. No LLM,
no network, no connector, no UI dependency, no hidden matching, no
filesystem writes — callers own persistence.

Golden-scope adapter. The reviewed parsers and the security gate are
contract-bound to bid-shaped identifiers (``SecurityClearedArtifact``
carries a ``BidId``). This slice reuses them *unchanged* rather than
forking a second parser stack, through a reserved internal namespace
(:data:`GOLDEN_SCOPE_BID_ID` and friends). Those values exist only while
a parser call is on the stack: everything this module returns is built
from golden contracts, which have no field that could carry them. This
coupling is a documented pilot boundary — the clean cut is a
domain-neutral parser core, which is a separate change.

Failure model: everything fails closed **per source**. A refused gate
verdict, a parser error, or a hash mismatch produces an outcome with an
operator-safe static reason and *no* document — never a partial one, and
never an exception that aborts a whole dataset run. Failure reasons are
drawn from fixed allowlists; raw exception text from a parse of real
internal content is never propagated.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from bidfusion.document_understanding.canonical import (
    ParsedContent,
    ParserError,
    UnsupportedDocumentError,
    operator_safe_parser_message,
    sanitize_error_code,
)
from bidfusion.document_understanding.parsers import parser_for
from bidfusion.golden_dataset.contracts import (
    ExtractionStatus,
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeDocument,
    KnowledgeProvenance,
    KnowledgeSection,
    KnowledgeSource,
    KnowledgeSourceLocator,
    ParseStatus,
    ProvenanceStatus,
)
from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.schemas.common import SecurityVerdict
from bidfusion.schemas.document import Page, TableCell
from bidfusion.schemas.security import SecurityClearedArtifact
from bidfusion.security import DeterministicPreflightScanner, decide_document

#: Reserved golden-scope namespace for the bid-shaped parser contracts.
#: These values never appear in any golden artifact; see the module
#: docstring. The all-zero forms are outside every real allocator's range.
GOLDEN_SCOPE_BID_ID = "BID-0000-000000"
GOLDEN_SCOPE_RUN_ID = "RUN-00000000-0000"
GOLDEN_SCOPE_DOCUMENT_ID = "DOC-000000"
GOLDEN_SCOPE_RAW_ARTIFACT_ID = "ART-00000000-000000"
GOLDEN_SCOPE_CANONICAL_ARTIFACT_ID = "ART-00000000-000001"

#: Static, operator-safe failure reasons. Nothing outside this table may
#: ever surface as a failure reason.
_REASON_HASH_MISMATCH = "supplied bytes do not match the inventoried source hash"
_REASON_GATE_BLOCKED = "the security gate blocked this source"
_REASON_GATE_REVIEW = "the security gate requires manual review of this source"
_REASON_NO_PARSER = "no reviewed parser exists for this source format"

_INGESTION_TIMESTAMP = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

#: Section collector used by the per-format normalizers.
_AddSection = Callable[[str | None, str, KnowledgeSourceLocator | None], None]


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Per-source result: updated inventory record, document or reason."""

    source: KnowledgeSource
    document: KnowledgeDocument | None
    failure_reason: str | None


class GoldenDatasetIngestionService:
    """Ingest inventoried golden sources one at a time, fail closed."""

    def __init__(self, *, scanner: DeterministicPreflightScanner | None = None) -> None:
        self._scanner = scanner or DeterministicPreflightScanner()

    def ingest_source(self, source: KnowledgeSource, content: bytes) -> IngestionOutcome:
        """Ingest one source; every failure is an outcome, not an exception."""
        parser = parser_for(source.extension)
        if parser is None:
            return IngestionOutcome(
                source=_advance(source, ParseStatus.PARSE_UNSUPPORTED, IngestionStatus.INVENTORIED),
                document=None,
                failure_reason=_REASON_NO_PARSER,
            )

        if sha256(content).hexdigest() != source.source_hash:
            return _failed(source, ParseStatus.NOT_PARSED, _REASON_HASH_MISMATCH)

        cleared, gate_reason = self._clear_through_real_gate(source, content)
        if cleared is None:
            return _failed(source, ParseStatus.NOT_PARSED, gate_reason)

        try:
            parsed = parser.parse(
                cleared=cleared,
                content=content,
                filename=source.filename,
                canonical_artifact_id=GOLDEN_SCOPE_CANONICAL_ARTIFACT_ID,
            )
        except ParserError as failure:
            code = sanitize_error_code(failure.error_code)
            return _failed(source, ParseStatus.PARSE_FAILED, operator_safe_parser_message(code))

        sections, provenance_status = _normalize(parsed, source)
        if not sections:
            return _failed(
                source,
                ParseStatus.PARSE_FAILED,
                operator_safe_parser_message(UnsupportedDocumentError.error_code),
            )

        document = KnowledgeDocument(
            knowledge_document_id=_knowledge_document_id(source),
            source_id=source.source_id,
            schema_version="1.0.0",
            title=(parsed.title or source.filename).strip() or source.filename,
            service_family=source.service_family,
            technology=source.technology,
            document_type=source.document_type,
            source_version=source.version,
            sections=tuple(sections),
            provenance=KnowledgeProvenance(
                source_id=source.source_id,
                filename=source.filename,
                source_hash=source.source_hash,
                document_version=source.version,
                locator=KnowledgeSourceLocator(whole_document=True),
            ),
            extraction_status=(
                ExtractionStatus.EXTRACTED if not parsed.warnings else ExtractionStatus.PARTIAL
            ),
            review_status=HumanReviewStatus.REQUIRED,
            provenance_status=provenance_status,
        )
        return IngestionOutcome(
            source=_advance(source, ParseStatus.PARSED, IngestionStatus.INGESTED),
            document=document,
            failure_reason=None,
        )

    def _clear_through_real_gate(
        self, source: KnowledgeSource, content: bytes
    ) -> tuple[SecurityClearedArtifact | None, str]:
        """Run the real preflight and gate policy under the golden scope."""
        artifact = ArtifactReference(
            artifact_id=GOLDEN_SCOPE_RAW_ARTIFACT_ID,
            bid_id=GOLDEN_SCOPE_BID_ID,
            run_id=GOLDEN_SCOPE_RUN_ID,
            artifact_type=ArtifactType.RAW_DOCUMENT,
            schema_version="1.0.0",
            content_ref=f"golden/{source.source_id}",
            content_hash=source.source_hash,
        )
        assessment = self._scanner.assess(
            artifact=artifact,
            document_id=GOLDEN_SCOPE_DOCUMENT_ID,
            filename=source.filename,
            content=content,
            assessed_at=_INGESTION_TIMESTAMP,
        )
        result = decide_document(assessment, decided_at=_INGESTION_TIMESTAMP)
        if result.verdict is not SecurityVerdict.ALLOW:
            reason = (
                _REASON_GATE_BLOCKED
                if result.verdict is SecurityVerdict.BLOCK
                else _REASON_GATE_REVIEW
            )
            return None, reason
        return (
            SecurityClearedArtifact(
                artifact=artifact,
                document_id=GOLDEN_SCOPE_DOCUMENT_ID,
                security_result=result,
            ),
            "",
        )


def _advance(
    source: KnowledgeSource, parse_status: ParseStatus, ingestion_status: IngestionStatus
) -> KnowledgeSource:
    return source.model_copy(
        update={"parse_status": parse_status, "ingestion_status": ingestion_status}
    )


def _failed(source: KnowledgeSource, parse_status: ParseStatus, reason: str) -> IngestionOutcome:
    return IngestionOutcome(
        source=_advance(source, parse_status, IngestionStatus.INGESTION_FAILED),
        document=None,
        failure_reason=reason,
    )


def _knowledge_document_id(source: KnowledgeSource) -> str:
    digest = sha256(f"{source.filename}\n{source.source_hash}".encode()).hexdigest()
    return f"GKD-{digest[24:36]}"


def _normalize(
    parsed: ParsedContent, source: KnowledgeSource
) -> tuple[list[KnowledgeSection], ProvenanceStatus]:
    """Flatten parsed pages into ordered sections with honest locators.

    Locators are translated from what each reviewed parser actually
    provides — never invented. Any section that ends up with only a
    ``whole_document`` locator marks the whole document
    ``PROVENANCE_PARTIAL``.
    """
    sections: list[KnowledgeSection] = []
    partial = False

    def add(heading: str | None, text: str, locator: KnowledgeSourceLocator | None) -> None:
        nonlocal partial
        body = text.strip()
        if not body:
            return
        if locator is None:
            locator = KnowledgeSourceLocator(whole_document=True)
            partial = True
        sections.append(
            KnowledgeSection(
                section_id=f"SEC-{len(sections):04d}",
                heading=heading,
                text=body,
                source_locator=locator,
                source_id=source.source_id,
            )
        )

    for page in parsed.pages:
        _normalize_page(page, source.extension, add)

    status = ProvenanceStatus.PROVENANCE_PARTIAL if partial else ProvenanceStatus.PROVENANCE_FULL
    return sections, status


def _normalize_page(
    page: Page,
    extension: str,
    add: _AddSection,
) -> None:
    if extension in ("xlsx",):
        for table in page.tables:
            cells = [cell for row in table.rows for cell in row.cells]
            text = "\n".join(
                " | ".join(cell.text for cell in row.cells if cell.text) for row in table.rows
            )
            add(table.caption, text, _sheet_locator(table.caption, cells))
        return

    if extension in ("docx",):
        _normalize_docx_page(page, add)
        return

    # PDF and plain text: one section per page, located by page number.
    text = "\n".join(paragraph.text for paragraph in page.paragraphs)
    if text.strip():
        add(None, text, KnowledgeSourceLocator(page=page.page_number))


def _normalize_docx_page(page: Page, add: _AddSection) -> None:
    titles = {section.section_id: section.title for section in page.sections}
    groups: dict[str | None, list[tuple[int | None, str]]] = {}
    order: list[str | None] = []
    for paragraph in page.paragraphs:
        key = paragraph.section_id
        index = _paragraph_index(paragraph.paragraph_id)
        if key is not None and paragraph.text == titles.get(key):
            continue  # the heading itself is the section title, not body text
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((index, paragraph.text))

    for key in order:
        entries = groups[key]
        heading = titles.get(key) if key is not None else None
        first_index = next((index for index, _ in entries if index is not None), None)
        locator = (
            KnowledgeSourceLocator(paragraph_index=first_index, heading=heading)
            if first_index is not None
            else None
        )
        add(heading, "\n".join(text for _, text in entries), locator)

    for table in page.tables:
        text = "\n".join(
            " | ".join(cell.text for cell in row.cells if cell.text) for row in table.rows
        )
        add(None, text, KnowledgeSourceLocator(table=table.table_id))


def _sheet_locator(
    caption: str | None, cells: Sequence[TableCell]
) -> KnowledgeSourceLocator | None:
    coordinates = [cell.cell_id.split("!", 1)[1] for cell in cells if "!" in cell.cell_id]
    if caption is None or not coordinates:
        return None
    return KnowledgeSourceLocator(sheet=caption, cell_range=f"{coordinates[0]}:{coordinates[-1]}")


def _paragraph_index(paragraph_id: str) -> int | None:
    tail = paragraph_id.rsplit("-", 1)[-1]
    if tail.isascii() and tail.isdigit():
        return int(tail)
    return None
