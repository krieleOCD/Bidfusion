"""Golden Knowledge UI pages: honest labels, no paths, no raw internals.

Every store used here is written in a temporary directory from synthetic
models. No test reads the real local dataset or the real runtime store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask.testing import FlaskClient

from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ConfidenceBand,
    DocumentType,
    EvidenceReference,
    ExtractionStatus,
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeDocument,
    KnowledgeInventory,
    KnowledgeProvenance,
    KnowledgeSection,
    KnowledgeSource,
    KnowledgeSourceLocator,
    ParseStatus,
    ParseSupport,
    ProvenanceStatus,
    ServiceFamily,
    Technology,
)
from bidfusion.golden_dataset.store import GoldenKnowledgeStore
from bidfusion.local_ui.app import create_app

_HASH = "d" * 64


def _source(
    filename: str,
    *,
    source_id: str,
    extension: str = "docx",
    technology: Technology = Technology.SPLUNK,
    parse_support: ParseSupport = ParseSupport.SUPPORTED,
    parse_status: ParseStatus = ParseStatus.PARSED,
    ingestion_status: IngestionStatus = IngestionStatus.INGESTED,
) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=source_id,
        filename=filename,
        extension=extension,
        file_size=100,
        source_hash=_HASH,
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=technology,
        document_type=DocumentType.SERVICE_DESCRIPTION,
        version="1.0",
        parse_support=parse_support,
        parse_status=parse_status,
        ingestion_status=ingestion_status,
        review_status=HumanReviewStatus.REQUIRED,
        provenance_id="GPV-000000000abc",
    )


def _populated_store(root: Path) -> GoldenKnowledgeStore:
    store = GoldenKnowledgeStore(root)
    store.write_inventory(
        KnowledgeInventory(
            dataset_label="synthetic-ui-set",
            sources=(
                _source("SD-Synthetic-Splunk v1.0.docx", source_id="GKS-00000000000a"),
                _source(
                    "CP-Synthetic Presentation.pptx",
                    source_id="GKS-00000000000b",
                    extension="pptx",
                    parse_support=ParseSupport.UNSUPPORTED,
                    parse_status=ParseStatus.PARSE_UNSUPPORTED,
                    ingestion_status=IngestionStatus.INVENTORIED,
                ),
            ),
        )
    )
    store.write_document(
        KnowledgeDocument(
            knowledge_document_id="GKD-00000000000a",
            source_id="GKS-00000000000a",
            schema_version="1.0.0",
            title="Synthetic document",
            service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
            technology=Technology.MICROSOFT_SENTINEL,
            document_type=DocumentType.SERVICE_DESCRIPTION,
            source_version="1.0",
            sections=(
                KnowledgeSection(
                    section_id="SEC-0001",
                    heading=None,
                    text="Synthetic section body.",
                    source_locator=KnowledgeSourceLocator(paragraph_index=1),
                    source_id="GKS-00000000000a",
                ),
            ),
            provenance=KnowledgeProvenance(
                source_id="GKS-00000000000a",
                filename="SD-Synthetic-Splunk v1.0.docx",
                source_hash=_HASH,
                document_version="1.0",
                locator=KnowledgeSourceLocator(whole_document=True),
            ),
            extraction_status=ExtractionStatus.EXTRACTED,
            review_status=HumanReviewStatus.REQUIRED,
            provenance_status=ProvenanceStatus.PROVENANCE_FULL,
        )
    )
    store.write_claims(
        (
            CapabilityClaim(
                claim_id="GCL-00000000000a",
                service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
                technology=Technology.MICROSOFT_SENTINEL,
                capability=CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,
                statement="Synthetic claim statement.",
                evidence_refs=(
                    EvidenceReference(
                        source_id="GKS-00000000000a",
                        section_id="SEC-0001",
                        locator=KnowledgeSourceLocator(paragraph_index=1),
                        source_version="1.0",
                    ),
                ),
                confidence_band=ConfidenceBand.MEDIUM,
            ),
        )
    )
    return store


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "golden_store"


@pytest.fixture
def client(store_root: Path) -> FlaskClient:
    _populated_store(store_root)
    return create_app(golden_store_root=store_root).test_client()


class TestInventoryPage:
    def test_renders_with_counts_and_rows(self, client: FlaskClient) -> None:
        response = client.get("/golden-knowledge")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "SD-Synthetic-Splunk v1.0.docx" in html
        assert "CP-Synthetic Presentation.pptx" in html

    def test_carries_the_honest_labels(self, client: FlaskClient) -> None:
        html = client.get("/golden-knowledge").get_data(as_text=True)
        assert "INTERNAL KNOWLEDGE" in html
        assert "LOCAL DATASET" in html
        assert "NOT COMMITTED TO REPOSITORY" in html
        assert "HUMAN REVIEW REQUIRED" in html

    def test_unsupported_pptx_is_visible_but_marked_unsupported(self, client: FlaskClient) -> None:
        html = client.get("/golden-knowledge").get_data(as_text=True)
        assert "PARSE UNSUPPORTED" in html

    def test_no_absolute_path_is_rendered(self, client: FlaskClient, store_root: Path) -> None:
        html = client.get("/golden-knowledge").get_data(as_text=True)
        assert str(store_root) not in html
        assert str(store_root.parent) not in html

    def test_empty_store_renders_an_honest_empty_state(self, tmp_path: Path) -> None:
        client = create_app(golden_store_root=tmp_path / "empty").test_client()
        response = client.get("/golden-knowledge")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "INTERNAL KNOWLEDGE" in html
        assert "no local golden knowledge store" in html.lower()

    def test_corrupt_store_never_leaks_a_raw_exception(self, tmp_path: Path) -> None:
        root = tmp_path / "broken"
        GoldenKnowledgeStore(root)  # creates the directories
        (root / "inventory.json").write_text("{not json")
        client = create_app(golden_store_root=root).test_client()
        response = client.get("/golden-knowledge")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Traceback" not in html
        assert "ValidationError" not in html
        assert "could not be read" in html


class TestDanglingEvidence:
    def test_matching_page_never_renders_claims_with_dangling_evidence(
        self, tmp_path: Path
    ) -> None:
        """Claims whose evidence does not resolve are a corrupt store, not data."""
        root = tmp_path / "dangling"
        store = _populated_store(root)
        assert store.read_inventory() is not None
        # remove every stored document so the claims' evidence dangles
        for document_file in (root / "documents").glob("GKD-*.json"):
            document_file.unlink()
        client = create_app(golden_store_root=root).test_client()
        response = client.get("/golden-knowledge/matching")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Synthetic claim statement." not in html
        assert "Traceback" not in html
        assert "could not be read" in html


class TestMatchingPage:
    def test_renders_matches_with_synthetic_requirement_label(self, client: FlaskClient) -> None:
        response = client.get("/golden-knowledge/matching")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "SYNTHETIC DEMO INPUT" in html
        assert "Microsoft Sentinel" in html

    def test_every_match_shows_human_review_required(self, client: FlaskClient) -> None:
        html = client.get("/golden-knowledge/matching").get_data(as_text=True)
        assert "HUMAN REVIEW REQUIRED" in html

    def test_matching_page_marks_the_pilot_as_deterministic(self, client: FlaskClient) -> None:
        html = client.get("/golden-knowledge/matching").get_data(as_text=True)
        assert "DETERMINISTIC PILOT MATCH" in html

    def test_no_absolute_path_on_the_matching_page(
        self, client: FlaskClient, store_root: Path
    ) -> None:
        html = client.get("/golden-knowledge/matching").get_data(as_text=True)
        assert str(store_root) not in html
