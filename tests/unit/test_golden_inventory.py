"""Read-only inventory tests over synthetic directories only."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from bidfusion.golden_dataset.contracts import (
    DocumentType,
    IngestionStatus,
    ParseStatus,
    ParseSupport,
    Technology,
)
from bidfusion.golden_dataset.inventory import build_inventory


def _write(directory: Path, name: str, content: bytes = b"synthetic bytes") -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestDiscovery:
    def test_supported_file_is_discovered_and_classified(self, tmp_path: Path) -> None:
        _write(tmp_path, "SD-Example Service-Splunk v2026.2.docx", b"synthetic docx bytes")
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        assert len(result.inventory.sources) == 1
        source = result.inventory.sources[0]
        assert source.document_type is DocumentType.SERVICE_DESCRIPTION
        assert source.technology is Technology.SPLUNK
        assert source.version == "2026.2"
        assert source.parse_support is ParseSupport.SUPPORTED
        assert source.parse_status is ParseStatus.NOT_PARSED
        assert source.ingestion_status is IngestionStatus.INVENTORIED

    def test_unsupported_pptx_is_inventoried_not_dropped(self, tmp_path: Path) -> None:
        _write(tmp_path, "CP-Example Presentation.pptx")
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        source = result.inventory.sources[0]
        assert source.parse_support is ParseSupport.UNSUPPORTED
        assert source.parse_status is ParseStatus.PARSE_UNSUPPORTED
        assert source.ingestion_status is IngestionStatus.INVENTORIED

    def test_hidden_files_are_excluded(self, tmp_path: Path) -> None:
        _write(tmp_path, ".DS_Store")
        _write(tmp_path, "OV-Example Overview.docx")
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        assert [source.filename for source in result.inventory.sources] == [
            "OV-Example Overview.docx"
        ]

    def test_missing_directory_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            build_inventory(tmp_path / "does-not-exist", dataset_label="synthetic-test-set")


class TestIdentityAndHashing:
    def test_source_hash_is_the_sha256_of_the_bytes(self, tmp_path: Path) -> None:
        content = b"synthetic stable content"
        _write(tmp_path, "OV-Example Overview.docx", content)
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        assert result.inventory.sources[0].source_hash == sha256(content).hexdigest()

    def test_inventory_is_stable_across_runs(self, tmp_path: Path) -> None:
        _write(tmp_path, "OV-Example Overview.docx", b"synthetic stable content")
        first = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        second = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        assert first.inventory == second.inventory

    def test_same_content_under_two_names_gets_distinct_ids(self, tmp_path: Path) -> None:
        content = b"identical synthetic content"
        _write(tmp_path, "OV-Example Overview.docx", content)
        _write(tmp_path, "SC-Example Catalogue.docx", content)
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        ids = {source.source_id for source in result.inventory.sources}
        assert len(ids) == 2

    def test_duplicate_name_and_content_is_reported_once(self, tmp_path: Path) -> None:
        content = b"identical synthetic content"
        _write(tmp_path, "OV-Example Overview.docx", content)
        _write(tmp_path, "nested/OV-Example Overview.docx", content)
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        assert len(result.inventory.sources) == 1
        assert any("duplicate" in warning for warning in result.inventory.warnings)


class TestSymlinkBoundary:
    """Symlinks are never followed — not even inside the source root.

    The approved source root is a trust boundary; a link is an escape
    hatch through it, so the pilot rejects every symlink outright
    (M-2 review finding).
    """

    def test_file_symlink_to_external_target_is_skipped_unread(self, tmp_path: Path) -> None:
        root = tmp_path / "source"
        root.mkdir()
        outside = tmp_path / "outside-secret.docx"
        outside.write_bytes(b"external bytes that must never be read")
        outside.chmod(0o000)
        try:
            (root / "SD-Link.docx").symlink_to(outside)
            _write(root, "OV-Legit Overview.docx")
            result = build_inventory(root, dataset_label="synthetic-test-set")
        finally:
            outside.chmod(0o600)
        assert [s.filename for s in result.inventory.sources] == ["OV-Legit Overview.docx"]
        assert any("symbolic link" in warning for warning in result.inventory.warnings)

    def test_file_symlink_to_internal_target_is_also_skipped(self, tmp_path: Path) -> None:
        real = _write(tmp_path / "source", "OV-Real Overview.docx")
        (tmp_path / "source" / "SD-Alias.docx").symlink_to(real)
        result = build_inventory(tmp_path / "source", dataset_label="synthetic-test-set")
        assert [s.filename for s in result.inventory.sources] == ["OV-Real Overview.docx"]

    def test_directory_symlink_is_not_traversed(self, tmp_path: Path) -> None:
        root = tmp_path / "source"
        root.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "SD-Outside Document.docx").write_bytes(b"outside")
        (root / "linked-dir").symlink_to(elsewhere)
        _write(root, "OV-Legit Overview.docx")
        result = build_inventory(root, dataset_label="synthetic-test-set")
        assert [s.filename for s in result.inventory.sources] == ["OV-Legit Overview.docx"]

    def test_dangling_symlink_is_skipped_safely(self, tmp_path: Path) -> None:
        root = tmp_path / "source"
        root.mkdir()
        (root / "SD-Dangling.docx").symlink_to(tmp_path / "never-existed.docx")
        _write(root, "OV-Legit Overview.docx")
        result = build_inventory(root, dataset_label="synthetic-test-set")
        assert [s.filename for s in result.inventory.sources] == ["OV-Legit Overview.docx"]

    def test_no_symlink_target_path_reaches_the_serialized_inventory(self, tmp_path: Path) -> None:
        root = tmp_path / "source"
        root.mkdir()
        target = tmp_path / "target-directory-name" / "secret-target-name.docx"
        target.parent.mkdir()
        target.write_bytes(b"bytes")
        (root / "SD-Link.docx").symlink_to(target)
        _write(root, "OV-Legit Overview.docx")
        payload = build_inventory(
            root, dataset_label="synthetic-test-set"
        ).inventory.model_dump_json()
        assert "secret-target-name" not in payload
        assert "target-directory-name" not in payload

    def test_symlink_handling_is_deterministic(self, tmp_path: Path) -> None:
        root = tmp_path / "source"
        root.mkdir()
        (root / "SD-Link.docx").symlink_to(tmp_path / "missing.docx")
        _write(root, "OV-Legit Overview.docx")
        first = build_inventory(root, dataset_label="synthetic-test-set")
        second = build_inventory(root, dataset_label="synthetic-test-set")
        assert first.inventory == second.inventory


class TestPathContainment:
    def test_serialized_inventory_carries_no_directory_path(self, tmp_path: Path) -> None:
        _write(tmp_path, "OV-Example Overview.docx")
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        payload = result.inventory.model_dump_json()
        assert str(tmp_path) not in payload
        assert tmp_path.name not in payload

    def test_local_paths_stay_on_the_runtime_side(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "OV-Example Overview.docx")
        result = build_inventory(tmp_path, dataset_label="synthetic-test-set")
        record = result.files[0]
        assert record.path == path
        assert record.source == result.inventory.sources[0]
