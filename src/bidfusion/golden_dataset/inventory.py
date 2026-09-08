"""Read-only inventory of a local golden knowledge source directory.

The inventory never opens document *content* beyond streaming bytes into
a SHA-256 hash: classification is filename-only, so this step is safe to
run over real internal documents before any parser is involved.

Local paths are runtime-only. The serialized :class:`KnowledgeInventory`
holds filenames and hashes; the ``source_id -> Path`` mapping travels
separately in :class:`InventoriedFile` records that must never be
serialized or rendered. Hidden files (``.DS_Store`` and friends) are OS
metadata, not knowledge sources, and are excluded by rule. Symlinks are
never followed — not even ones resolving inside the source root: the
root is a trust boundary, so every link is skipped unopened with a
warning naming only the link itself, never its target.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from bidfusion.document_understanding.parsers import SUPPORTED_FILE_TYPES
from bidfusion.golden_dataset.classification import classify_filename
from bidfusion.golden_dataset.contracts import (
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeInventory,
    KnowledgeSource,
    ParseStatus,
    ParseSupport,
)
from bidfusion.shared.filetype import extension_of

_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class InventoriedFile:
    """One inventory record paired with its runtime-only local path."""

    source: KnowledgeSource
    path: Path


@dataclass(frozen=True, slots=True)
class InventoryResult:
    """Serializable inventory plus the runtime-only path mapping."""

    inventory: KnowledgeInventory
    files: tuple[InventoriedFile, ...]


def source_identity(filename: str, content_hash: str) -> tuple[str, str]:
    """Deterministic ``(source_id, provenance_id)`` for one source.

    Derived from filename *and* content hash so renamed copies stay
    distinguishable while re-runs over unchanged files are stable.
    """
    digest = sha256(f"{filename}\n{content_hash}".encode()).hexdigest()
    return f"GKS-{digest[:12]}", f"GPV-{digest[12:24]}"


def build_inventory(source_dir: Path, *, dataset_label: str) -> InventoryResult:
    """Inventory every visible file under ``source_dir``, read-only."""
    if not source_dir.is_dir():
        msg = "golden source directory does not exist or is not a directory"
        raise FileNotFoundError(msg)

    records: dict[str, InventoriedFile] = {}
    warnings: list[str] = []
    for path in sorted(source_dir.rglob("*"), key=lambda item: (item.name, str(item))):
        if path.is_symlink():
            # The source root is a trust boundary and a symlink is an
            # escape hatch through it. Every symlink — file, directory,
            # or dangling, even one resolving inside the root — is
            # skipped without ever being opened, and only the link's own
            # name is recorded, never its target.
            warnings.append(f"symbolic link skipped: {path.name}")
            continue
        if not path.is_file() or _is_hidden(path, source_dir):
            continue
        record = _inventory_file(path)
        existing = records.get(record.source.source_id)
        if existing is not None:
            warnings.append(
                f"duplicate source skipped: {record.source.filename} "
                f"(same name and content as {existing.source.source_id})"
            )
            continue
        records[record.source.source_id] = record

    files = tuple(sorted(records.values(), key=lambda item: item.source.filename))
    return InventoryResult(
        inventory=KnowledgeInventory(
            dataset_label=dataset_label,
            sources=tuple(record.source for record in files),
            warnings=tuple(warnings),
        ),
        files=files,
    )


def _inventory_file(path: Path) -> InventoriedFile:
    content_hash, size = _stream_sha256(path)
    classified = classify_filename(path.name)
    extension = extension_of(path.name) or "none"
    supported = extension in SUPPORTED_FILE_TYPES
    source_id, provenance_id = source_identity(path.name, content_hash)
    source = KnowledgeSource(
        source_id=source_id,
        filename=path.name,
        extension=extension,
        file_size=size,
        source_hash=content_hash,
        service_family=classified.service_family,
        technology=classified.technology,
        document_type=classified.document_type,
        version=classified.version,
        parse_support=ParseSupport.SUPPORTED if supported else ParseSupport.UNSUPPORTED,
        parse_status=ParseStatus.NOT_PARSED if supported else ParseStatus.PARSE_UNSUPPORTED,
        ingestion_status=IngestionStatus.INVENTORIED,
        review_status=HumanReviewStatus.REQUIRED,
        provenance_id=provenance_id,
    )
    return InventoriedFile(source=source, path=path)


def _is_hidden(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part.startswith(".") for part in relative.parts)


def _stream_sha256(path: Path) -> tuple[str, int]:
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
