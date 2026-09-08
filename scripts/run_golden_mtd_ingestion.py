"""Run the Golden Dataset MTD pilot over a local source directory.

Reads the source directory strictly read-only, writes exclusively into
the gitignored local runtime store (``runtime/golden_dataset`` by
default), and never prints or serializes the source path into any
artifact. The source directory is an operator-supplied argument — real
internal locations must never be hardcoded here.

Pipeline per run: inventory → security gate + safe parsing of the pilot
document families → rule-based claims → deterministic demo matching.
Everything is offline: no network, no LLM, no subprocess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidfusion.golden_dataset.claims import extract_claims  # noqa: E402
from bidfusion.golden_dataset.contracts import (  # noqa: E402
    DocumentType,
    IngestionStatus,
    KnowledgeInventory,
    KnowledgeSource,
    ParseSupport,
)
from bidfusion.golden_dataset.ingestion import GoldenDatasetIngestionService  # noqa: E402
from bidfusion.golden_dataset.inventory import build_inventory  # noqa: E402
from bidfusion.golden_dataset.matching import (  # noqa: E402
    SYNTHETIC_DEMO_REQUIREMENTS,
    match_requirements,
)
from bidfusion.golden_dataset.store import GoldenKnowledgeStore  # noqa: E402

#: Document families selected for deep pilot ingestion. Everything else
#: is fully inventoried but marked NOT_SELECTED for this slice.
PILOT_DOCUMENT_TYPES = frozenset(
    {
        DocumentType.SERVICE_DESCRIPTION,
        DocumentType.QA_TECHNOLOGY_GUIDANCE,
        DocumentType.SERVICE_ACTIVATION_PROCEDURE,
        DocumentType.SERVICE_INSTRUCTION,
        DocumentType.OVERVIEW,
        DocumentType.SERVICE_CATALOGUE,
        DocumentType.STATEMENT_OF_WORK,
    }
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--dataset-label", default="mtd-golden-pilot")
    arguments = parser.parse_args()

    store_root: Path = (
        arguments.store_root
        if arguments.store_root is not None
        else GoldenKnowledgeStore.default_root()
    )
    store = GoldenKnowledgeStore(store_root)
    service = GoldenDatasetIngestionService()

    result = build_inventory(arguments.source_dir, dataset_label=arguments.dataset_label)
    updated_sources: list[KnowledgeSource] = []
    documents = []
    failures: list[tuple[str, str]] = []

    for record in result.files:
        source = record.source
        if source.parse_support is ParseSupport.UNSUPPORTED:
            updated_sources.append(source)
            continue
        if source.document_type not in PILOT_DOCUMENT_TYPES:
            updated_sources.append(
                source.model_copy(update={"ingestion_status": IngestionStatus.NOT_SELECTED})
            )
            continue
        outcome = service.ingest_source(source, record.path.read_bytes())
        updated_sources.append(outcome.source)
        if outcome.document is not None:
            documents.append(outcome.document)
            store.write_document(outcome.document)
        elif outcome.failure_reason is not None:
            failures.append((source.filename, outcome.failure_reason))

    inventory = KnowledgeInventory(
        dataset_label=arguments.dataset_label,
        sources=tuple(updated_sources),
        warnings=result.inventory.warnings,
    )
    store.write_inventory(inventory)

    claims = extract_claims(tuple(documents))
    store.write_claims(claims)
    matches = match_requirements(SYNTHETIC_DEMO_REQUIREMENTS, claims)
    store.write_matches(matches)

    ingested = sum(
        1 for source in updated_sources if source.ingestion_status is IngestionStatus.INGESTED
    )
    print(f"inventoried sources : {len(updated_sources)}")
    print(f"ingested documents  : {ingested}")
    print(f"knowledge documents : {len(documents)}")
    print(f"capability claims   : {len(claims)}")
    print(f"demo matches        : {len(matches)}")
    for filename, reason in failures:
        print(f"failed closed       : {filename} -> {reason}")
    for warning in inventory.warnings:
        print(f"inventory warning   : {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
