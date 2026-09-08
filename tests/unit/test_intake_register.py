"""Tests for local package registration (intake)."""

from __future__ import annotations

import os
import types
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from bidfusion.intake import RegisteredPackage, register_package
from bidfusion.intake import register as register_module
from bidfusion.schemas import ArtifactType
from bidfusion.shared.identifiers import ArtifactIdAllocator, run_id_for

BID_ID = "BID-2026-000123"
STARTED_AT = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)


def register(
    package_dir: Path,
    *,
    max_file_size_bytes: int = 100 * 1024 * 1024,
) -> RegisteredPackage:
    return register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
        max_file_size_bytes=max_file_size_bytes,
    )


def test_registration_orders_nested_files_and_binds_exact_hashes(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    (package_dir / "annex").mkdir(parents=True)
    (package_dir / "main.pdf").write_bytes(b"%PDF-1.4 synthetic")
    (package_dir / "annex" / "matrix.xlsx").write_bytes(b"PK\x03\x04synthetic")
    (package_dir / "notes.txt").write_bytes(b"synthetic notes")

    package = register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
    )

    assert package.package_name == "package"
    assert [item.document.document_id for item in package.documents] == [
        "DOC-001",
        "DOC-002",
        "DOC-003",
    ]
    assert [item.document.filename for item in package.documents] == [
        "annex/matrix.xlsx",
        "main.pdf",
        "notes.txt",
    ]
    for item in package.documents:
        document = item.document
        assert document.bid_id == BID_ID
        assert document.artifact.artifact_type is ArtifactType.RAW_DOCUMENT
        assert document.sha256 == sha256(item.content).hexdigest()
        assert document.artifact.content_hash == document.sha256
        assert document.artifact.content_ref == f"package/{document.filename}"
        assert document.size_bytes == len(item.content)
    assert package.documents[0].document.mime_type.endswith("spreadsheetml.sheet")
    assert package.documents[1].document.file_type == "pdf"


def test_hidden_files_are_skipped_and_symlinks_are_explicitly_rejected(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / ".hidden.txt").write_bytes(b"hidden")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    (package_dir / "linked.txt").symlink_to(outside)
    (package_dir / "kept.txt").write_bytes(b"kept")

    package = register(package_dir)

    assert tuple(item.document.filename for item in package.documents) == ("kept.txt",)
    assert len(package.rejected) == 1
    assert package.rejected[0].filename == "linked.txt"
    assert "symbolic link" in package.rejected[0].reason


def test_oversized_files_are_rejected_before_a_full_read(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "huge.txt").write_bytes(b"x" * 1024)
    (package_dir / "small.txt").write_bytes(b"ok")

    package = register(package_dir, max_file_size_bytes=16)

    assert tuple(item.document.filename for item in package.documents) == ("small.txt",)
    assert package.rejected[0].filename == "huge.txt"
    assert "exceeds the intake limit" in package.rejected[0].reason


def test_non_regular_files_are_rejected(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    os.mkfifo(package_dir / "pipe.txt")
    (package_dir / "kept.txt").write_bytes(b"kept")

    package = register(package_dir)

    assert tuple(item.document.filename for item in package.documents) == ("kept.txt",)
    assert package.rejected[0].filename == "pipe.txt"
    assert "not a regular file" in package.rejected[0].reason


def test_files_changing_during_read_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "racy.txt").write_bytes(b"initial content")

    real_fstat = os.fstat
    calls = {"count": 0}

    def racing_fstat(descriptor: int) -> object:
        result = real_fstat(descriptor)
        calls["count"] += 1
        if calls["count"] % 2 == 0:
            return types.SimpleNamespace(
                st_mode=result.st_mode,
                st_size=result.st_size + 1,
                st_mtime_ns=result.st_mtime_ns + 1,
            )
        return result

    monkeypatch.setattr(register_module, "_fstat", racing_fstat)
    package = register(package_dir)

    assert package.documents == ()
    assert package.rejected[0].filename == "racy.txt"
    assert "changed while it was being read" in package.rejected[0].reason


def test_chunked_hashing_matches_a_whole_file_digest(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    content = bytes(range(256)) * (10 * 1024)  # 2.5 MiB spans multiple chunks
    (package_dir / "large.bin").write_bytes(content)

    package = register(package_dir)

    document = package.documents[0].document
    assert package.rejected == ()
    assert document.sha256 == sha256(content).hexdigest()
    assert package.documents[0].content == content
    assert document.size_bytes == len(content)


def test_registration_is_deterministic_for_identical_inputs(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "a.txt").write_bytes(b"alpha")
    (package_dir / "b.txt").write_bytes(b"beta")

    first = register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
    )
    second = register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
    )

    assert [item.document for item in first.documents] == [
        item.document for item in second.documents
    ]


def test_empty_package_registers_no_documents(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    package = register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
    )

    assert package.documents == ()


def test_missing_package_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        register_package(
            tmp_path / "missing",
            bid_id=BID_ID,
            run_id=run_id_for(STARTED_AT),
            artifact_ids=ArtifactIdAllocator(STARTED_AT),
        )


def test_unknown_extension_gets_explicit_fallback_metadata(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "payload.js").write_bytes(b"// synthetic")

    package = register_package(
        package_dir,
        bid_id=BID_ID,
        run_id=run_id_for(STARTED_AT),
        artifact_ids=ArtifactIdAllocator(STARTED_AT),
    )

    document = package.documents[0].document
    assert document.file_type == "js"
    assert document.mime_type == "application/octet-stream"
