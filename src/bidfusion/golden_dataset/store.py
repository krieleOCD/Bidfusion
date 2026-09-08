"""Local runtime store for golden knowledge artifacts.

Real knowledge artifacts are derived from real internal documents and
therefore **never** belong in the repository: the default root is
``<checkout>/runtime/golden_dataset``, which is gitignored, and every
directory is created owner-only through :mod:`bidfusion.shared.secure_io`.
Serialized artifacts are the path-free golden contracts — filenames and
hashes only — so the store can be relocated or deleted without any file
carrying a trace of the local directory layout.

Layout under the root::

    inventory.json          one KnowledgeInventory snapshot
    documents/GKD-*.json    one KnowledgeDocument per file
    claims.json             the extracted CapabilityClaims
    matches.json            the deterministic pilot MatchCandidates
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from bidfusion.golden_dataset.contracts import (
    CapabilityClaim,
    KnowledgeDocument,
    KnowledgeInventory,
    MatchCandidate,
)
from bidfusion.shared.pathguards import repository_root
from bidfusion.shared.secure_io import ensure_private_directory, write_private_text

_CLAIMS_ADAPTER = TypeAdapter(tuple[CapabilityClaim, ...])
_MATCHES_ADAPTER = TypeAdapter(tuple[MatchCandidate, ...])

#: Static, content-free integrity failure text. Never interpolate a
#: claim, section, or identifier into it: the store holds real internal
#: content, and an integrity error must not echo any of it.
_INTEGRITY_MESSAGE = (
    "golden store claims reference evidence that does not resolve against "
    "the stored knowledge documents"
)


class GoldenStoreIntegrityError(RuntimeError):
    """The store is internally inconsistent and must not be presented.

    Raised when a schema-valid claim cites evidence the stored
    KnowledgeDocuments cannot back — a dangling source, a missing
    section, or a version drift. Fail closed: nothing is dropped or
    repaired, the load as a whole is refused (M-3 review finding).
    """


class GoldenKnowledgeStore:
    """Read/write golden artifacts under one private local root."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._documents = root / "documents"
        ensure_private_directory(self._root, root=root.parent if root.parent.exists() else None)
        ensure_private_directory(self._documents, root=self._root)

    @classmethod
    def default_root(cls) -> Path:
        """The gitignored runtime location inside this checkout."""
        checkout = repository_root()
        if checkout is None:
            msg = "no repository checkout found for the default golden store root"
            raise RuntimeError(msg)
        return checkout / "runtime" / "golden_dataset"

    @property
    def root(self) -> Path:
        return self._root

    def write_inventory(self, inventory: KnowledgeInventory) -> None:
        self._write(self._root / "inventory.json", inventory.model_dump_json(indent=2))

    def read_inventory(self) -> KnowledgeInventory | None:
        path = self._root / "inventory.json"
        if not path.is_file():
            return None
        return KnowledgeInventory.model_validate_json(path.read_text())

    def write_document(self, document: KnowledgeDocument) -> None:
        self._write(
            self._documents / f"{document.knowledge_document_id}.json",
            document.model_dump_json(indent=2),
        )

    def read_documents(self) -> tuple[KnowledgeDocument, ...]:
        return tuple(
            KnowledgeDocument.model_validate_json(path.read_text())
            for path in sorted(self._documents.glob("GKD-*.json"))
        )

    def write_claims(self, claims: tuple[CapabilityClaim, ...]) -> None:
        payload = json.dumps([json.loads(claim.model_dump_json()) for claim in claims], indent=2)
        self._write(self._root / "claims.json", payload)

    def read_claims(self) -> tuple[CapabilityClaim, ...]:
        """Load claims and verify every evidence reference resolves.

        Schema validation alone would accept a claim citing a source,
        section, or version this store no longer holds. Each reference
        is therefore resolved against the stored documents; any dangling
        or mismatched reference raises :class:`GoldenStoreIntegrityError`
        for the whole load — invalid evidence is never silently dropped.
        """
        path = self._root / "claims.json"
        if not path.is_file():
            return ()
        claims = _CLAIMS_ADAPTER.validate_json(path.read_text())
        _verify_evidence_resolves(claims, self.read_documents())
        return claims

    def write_matches(self, matches: tuple[MatchCandidate, ...]) -> None:
        payload = json.dumps([json.loads(match.model_dump_json()) for match in matches], indent=2)
        self._write(self._root / "matches.json", payload)

    def read_matches(self) -> tuple[MatchCandidate, ...]:
        path = self._root / "matches.json"
        if not path.is_file():
            return ()
        return _MATCHES_ADAPTER.validate_json(path.read_text())

    def _write(self, path: Path, text: str) -> None:
        write_private_text(path, text, root=self._root)


def _verify_evidence_resolves(
    claims: tuple[CapabilityClaim, ...],
    documents: tuple[KnowledgeDocument, ...],
) -> None:
    """Fail closed unless every evidence reference is backed by a document.

    Checked per reference: the source exists in this store snapshot, the
    cited section belongs to exactly that source's document, and the
    reference's source version matches the document's. Section IDs are
    only unique within one document, so membership is always checked
    against the document of the cited source, never globally.
    """
    by_source = {document.source_id: document for document in documents}
    for claim in claims:
        for reference in claim.evidence_refs:
            document = by_source.get(reference.source_id)
            if document is None:
                raise GoldenStoreIntegrityError(_INTEGRITY_MESSAGE)
            if reference.section_id not in {section.section_id for section in document.sections}:
                raise GoldenStoreIntegrityError(_INTEGRITY_MESSAGE)
            if reference.source_version != document.source_version:
                raise GoldenStoreIntegrityError(_INTEGRITY_MESSAGE)
