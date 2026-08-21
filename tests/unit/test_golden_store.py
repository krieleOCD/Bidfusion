"""Runtime store tests — synthetic artifacts in temporary directories only."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    MatchCandidate,
    MatchStatus,
    ParseStatus,
    ParseSupport,
    ProvenanceStatus,
    ServiceFamily,
    Technology,
)
from bidfusion.golden_dataset.store import GoldenKnowledgeStore, GoldenStoreIntegrityError

_HASH = "b" * 64


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        source_id="GKS-000000000abc",
        filename="SD-Synthetic-Splunk v1.0.docx",
        extension="docx",
        file_size=10,
        source_hash=_HASH,
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=Technology.SPLUNK,
        document_type=DocumentType.SERVICE_DESCRIPTION,
        version="1.0",
        parse_support=ParseSupport.SUPPORTED,
        parse_status=ParseStatus.PARSED,
        ingestion_status=IngestionStatus.INGESTED,
        review_status=HumanReviewStatus.REQUIRED,
        provenance_id="GPV-000000000abc",
    )


def _claim() -> CapabilityClaim:
    return CapabilityClaim(
        claim_id="GCL-000000000abc",
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=Technology.SPLUNK,
        capability=CapabilityCategory.SPLUNK_SUPPORT,
        statement="Synthetic claim statement.",
        evidence_refs=(
            EvidenceReference(
                source_id="GKS-000000000abc",
                section_id="SEC-0001",
                locator=KnowledgeSourceLocator(paragraph_index=1),
                source_version="1.0",
            ),
        ),
        confidence_band=ConfidenceBand.MEDIUM,
    )


def _document(
    *,
    source_id: str = "GKS-000000000abc",
    section_ids: tuple[str, ...] = ("SEC-0001",),
    source_version: str | None = "1.0",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        knowledge_document_id=f"GKD-{source_id[-12:]}",
        source_id=source_id,
        schema_version="1.0.0",
        title="Synthetic document",
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=Technology.SPLUNK,
        document_type=DocumentType.SERVICE_DESCRIPTION,
        source_version=source_version,
        sections=tuple(
            KnowledgeSection(
                section_id=section_id,
                heading=None,
                text="Synthetic section text.",
                source_locator=KnowledgeSourceLocator(paragraph_index=index),
                source_id=source_id,
            )
            for index, section_id in enumerate(section_ids)
        ),
        provenance=KnowledgeProvenance(
            source_id=source_id,
            filename="SD-Synthetic-Splunk v1.0.docx",
            source_hash=_HASH,
            document_version=source_version,
            locator=KnowledgeSourceLocator(whole_document=True),
        ),
        extraction_status=ExtractionStatus.EXTRACTED,
        review_status=HumanReviewStatus.REQUIRED,
        provenance_status=ProvenanceStatus.PROVENANCE_FULL,
    )


def _claim_with_evidence(
    *evidence: EvidenceReference,
) -> CapabilityClaim:
    return CapabilityClaim(
        claim_id="GCL-000000000abc",
        service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
        technology=Technology.SPLUNK,
        capability=CapabilityCategory.SPLUNK_SUPPORT,
        statement="Synthetic claim statement.",
        evidence_refs=evidence,
        confidence_band=ConfidenceBand.MEDIUM,
    )


def _reference(
    *,
    source_id: str = "GKS-000000000abc",
    section_id: str = "SEC-0001",
    source_version: str | None = "1.0",
) -> EvidenceReference:
    return EvidenceReference(
        source_id=source_id,
        section_id=section_id,
        locator=KnowledgeSourceLocator(paragraph_index=1),
        source_version=source_version,
    )


class TestEvidenceIntegrity:
    """`read_claims` must fail closed on evidence the store cannot back.

    A schema-valid claim whose evidence does not resolve against the
    stored KnowledgeDocuments is a corrupted store, never presentable
    data (M-3 review finding).
    """

    def _store_with_document(self, root: Path) -> GoldenKnowledgeStore:
        store = GoldenKnowledgeStore(root)
        store.write_document(_document())
        return store

    def test_resolving_evidence_loads(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference()),))
        assert len(store.read_claims()) == 1

    def test_unknown_source_id_fails_closed(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference(source_id="GKS-ffffffffffff")),))
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_unknown_section_id_fails_closed(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference(section_id="SEC-9999")),))
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_section_of_another_document_fails_closed(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        store.write_document(_document(section_ids=("SEC-0001",)))
        store.write_document(_document(source_id="GKS-000000000def", section_ids=("SEC-0005",)))
        store.write_claims((_claim_with_evidence(_reference(section_id="SEC-0005")),))
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_wrong_source_version_fails_closed(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference(source_version="9.9")),))
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_stale_evidence_after_document_removal_fails_closed(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference()),))
        document_file = next((tmp_path / "golden" / "documents").glob("GKD-*.json"))
        document_file.unlink()
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_one_dangling_reference_rejects_the_whole_load(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims(
            (
                _claim_with_evidence(
                    _reference(),
                    _reference(section_id="SEC-9999"),
                ),
            )
        )
        with pytest.raises(GoldenStoreIntegrityError):
            store.read_claims()

    def test_integrity_error_is_static_and_content_free(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference(section_id="SEC-9999")),))
        with pytest.raises(GoldenStoreIntegrityError) as failure:
            store.read_claims()
        message = str(failure.value)
        assert "Synthetic" not in message
        assert "SEC-9999" not in message
        assert "GKS-" not in message

    def test_valid_store_round_trip_is_deterministic(self, tmp_path: Path) -> None:
        store = self._store_with_document(tmp_path / "golden")
        store.write_claims((_claim_with_evidence(_reference()),))
        assert store.read_claims() == store.read_claims()


class TestRoundTrips:
    def test_inventory_round_trip(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        inventory = KnowledgeInventory(dataset_label="synthetic-test-set", sources=(_source(),))
        store.write_inventory(inventory)
        assert store.read_inventory() == inventory

    def test_claims_round_trip(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        store.write_document(_document())
        store.write_claims((_claim(),))
        assert store.read_claims() == (_claim(),)

    def test_matches_round_trip(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        match = MatchCandidate(
            requirement_id="DEMO-REQ-001",
            claim_id="GCL-000000000abc",
            match_status=MatchStatus.MATCHED,
            rationale="Synthetic rationale.",
            evidence_refs=(),
            human_review_status=HumanReviewStatus.REQUIRED,
        )
        store.write_matches((match,))
        assert store.read_matches() == (match,)

    def test_empty_store_reads_as_absent(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        assert store.read_inventory() is None
        assert store.read_documents() == ()
        assert store.read_claims() == ()
        assert store.read_matches() == ()


class TestContainment:
    def test_store_files_contain_no_store_path(self, tmp_path: Path) -> None:
        store = GoldenKnowledgeStore(tmp_path / "golden")
        store.write_inventory(
            KnowledgeInventory(dataset_label="synthetic-test-set", sources=(_source(),))
        )
        for file in (tmp_path / "golden").rglob("*.json"):
            assert str(tmp_path) not in file.read_text()

    def test_default_root_is_the_ignored_runtime_directory(self) -> None:
        root = GoldenKnowledgeStore.default_root()
        assert root.parts[-2:] == ("runtime", "golden_dataset")
        repo_root = root.parents[1]
        gitignore = (repo_root / ".gitignore").read_text()
        assert "runtime/" in gitignore.splitlines()
