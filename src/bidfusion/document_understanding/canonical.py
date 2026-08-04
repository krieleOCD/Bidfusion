"""Shared assembly of ``CanonicalDocument`` artifacts from cleared input.

Parsers in this package accept only a valid ``SecurityClearedArtifact``
plus the exact bytes it binds. They re-verify the SHA-256 binding before
touching the content and fail closed on any mismatch.

Canonical documents are sealed under the versioned, domain-separated hash
convention in :mod:`bidfusion.shared.payloads`: ``content_ref`` names the
canonical payload file and ``content_hash`` is the SHA-256 of exactly those
bytes, covering every non-envelope field automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol

from bidfusion.schemas.artifact import ArtifactType
from bidfusion.schemas.document import (
    CanonicalDocument,
    DocumentMetadata,
    Page,
)
from bidfusion.schemas.ids import ArtifactId, RunId
from bidfusion.schemas.provenance import SourceLocator, SourceReference
from bidfusion.schemas.security import SecurityClearedArtifact
from bidfusion.shared.payloads import seal_artifact

CANONICAL_SCHEMA_VERSION = "1.0.0"
CANONICAL_DOMAIN = "canonical_document"


class ParserError(RuntimeError):
    """Base class for document-understanding failures; always fail closed.

    ``error_code`` is a stable, content-free identifier. Exception *texts*
    may reference library details or document content and are therefore
    never persisted; only the code and its operator-safe message are.
    """

    error_code = "PARSER_FAILURE"


class UnsupportedDocumentError(ParserError):
    """The document type or content cannot be represented by this MVP slice."""

    error_code = "PARSER_UNSUPPORTED_CONTENT"


class DocumentParsingError(ParserError):
    """The document could not be parsed although it appeared supported."""

    error_code = "PARSER_TECHNICAL_FAILURE"


class ClearedContentMismatchError(DocumentParsingError):
    """The supplied bytes do not match the cleared artifact's content hash."""

    error_code = "PARSER_CLEARED_CONTENT_MISMATCH"


#: The fixed fallback code for anything outside the allowlist below.
GENERIC_PARSER_ERROR_CODE = "GENERIC_PARSER_FAILURE"

#: Allowlist of known-safe error codes with their static operator-safe
#: messages. These texts can never carry document content, secrets, or
#: library internals into persisted summaries, review packages, or CLI
#: output. Codes are *data* until they pass :func:`sanitize_error_code` —
#: an exception subclass could carry anything in ``error_code``.
PARSER_ERROR_MESSAGES = {
    "PARSER_FAILURE": ("the document could not be processed by the parser; manual review required"),
    "PARSER_UNSUPPORTED_CONTENT": (
        "the document content is not supported by the MVP parsers "
        "(for example scanned or empty pages); manual review required"
    ),
    "PARSER_TECHNICAL_FAILURE": (
        "the parser failed technically on this document; manual review required"
    ),
    "PARSER_CLEARED_CONTENT_MISMATCH": (
        "the document bytes do not match the security-cleared content; processing was refused"
    ),
    "PARSER_MISSING": ("no MVP parser exists for this file type; manual review required"),
    GENERIC_PARSER_ERROR_CODE: (
        "the document could not be processed (unrecognized parser failure); manual review required"
    ),
}


def sanitize_error_code(code: object) -> str:
    """Collapse anything outside the fixed allowlist to the generic code.

    Error codes originate from exception attributes and are therefore
    untrusted; only exact allowlist members may ever be persisted.
    """
    if isinstance(code, str) and code in PARSER_ERROR_MESSAGES:
        return code
    return GENERIC_PARSER_ERROR_CODE


def operator_safe_parser_message(code: str) -> str:
    """Static operator-safe message for one allowlisted parser error code."""
    return PARSER_ERROR_MESSAGES.get(code, PARSER_ERROR_MESSAGES[GENERIC_PARSER_ERROR_CODE])


@dataclass(frozen=True, slots=True)
class ParsedContent:
    """Intermediate parser output before canonical assembly."""

    pages: tuple[Page, ...]
    title: str | None = None
    warnings: tuple[str, ...] = ()


class DocumentParser(Protocol):
    """Structural contract implemented by every MVP document parser."""

    parser_name: str
    parser_version: str

    def parse(
        self,
        *,
        cleared: SecurityClearedArtifact,
        content: bytes,
        filename: str,
        canonical_artifact_id: ArtifactId,
    ) -> ParsedContent:
        """Parse cleared bytes into provenance-bound canonical pages."""
        ...


def verify_cleared_content(cleared: SecurityClearedArtifact, content: bytes) -> None:
    """Fail closed when bytes do not match the exact cleared content hash."""
    observed = sha256(content).hexdigest()
    if observed != cleared.artifact.content_hash:
        msg = "supplied content does not match the cleared artifact content hash"
        raise ClearedContentMismatchError(msg)


def block_source(
    cleared: SecurityClearedArtifact,
    *,
    filename: str,
    canonical_artifact_id: ArtifactId,
    locator: SourceLocator,
    quote: str | None = None,
) -> SourceReference:
    """Build one canonical-bound block provenance reference."""
    return SourceReference(
        bid_id=cleared.artifact.bid_id,
        document_id=cleared.document_id,
        filename=filename,
        document_hash=cleared.artifact.content_hash,
        locator=locator,
        canonical_artifact_id=canonical_artifact_id,
        quote=quote if quote else None,
    )


def build_canonical_document(
    cleared: SecurityClearedArtifact,
    parsed: ParsedContent,
    *,
    filename: str,
    canonical_artifact_id: ArtifactId,
    run_id: RunId,
    created_at: datetime,
    parser_name: str,
    parser_version: str,
) -> CanonicalDocument:
    """Assemble the validated canonical document with lineage and payload hash."""
    metadata = DocumentMetadata(
        title=parsed.title,
        page_count=len(parsed.pages),
        parser=parser_name,
        parser_version=parser_version,
    )
    document_source = SourceReference(
        bid_id=cleared.artifact.bid_id,
        document_id=cleared.document_id,
        filename=filename,
        document_hash=cleared.artifact.content_hash,
        locator=SourceLocator(whole_document=True),
    )
    return seal_artifact(
        lambda envelope: CanonicalDocument(
            artifact=envelope,
            source_artifact=cleared.artifact,
            document_id=cleared.document_id,
            bid_id=cleared.artifact.bid_id,
            metadata=metadata,
            pages=parsed.pages,
            source=document_source,
        ),
        artifact_id=canonical_artifact_id,
        bid_id=cleared.artifact.bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.CANONICAL_DOCUMENT,
        schema_version=CANONICAL_SCHEMA_VERSION,
        domain=CANONICAL_DOMAIN,
        content_ref=f"canonical/{cleared.document_id}-canonical.payload.json",
        producer_component=parser_name,
        producer_version=parser_version,
        input_artifacts=(cleared.artifact,),
        created_at=created_at,
    )
