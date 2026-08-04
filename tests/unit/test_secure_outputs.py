"""Tests for confidential-by-default, atomic output writing (F4)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from bidfusion.shared.secure_io import (
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    ensure_private_directory,
    write_private_bytes,
)


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_created_directories_and_files_are_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "bid" / "run" / "security" / "result.json"

    write_private_bytes(target, b'{"synthetic": true}')

    assert target.read_bytes() == b'{"synthetic": true}'
    assert mode_of(target) == PRIVATE_FILE_MODE
    assert mode_of(target.parent) == PRIVATE_DIR_MODE
    assert mode_of(target.parent.parent) == PRIVATE_DIR_MODE
    assert mode_of(target.parent.parent.parent) == PRIVATE_DIR_MODE
    # No group or world bits anywhere.
    assert mode_of(target) & 0o077 == 0
    assert mode_of(target.parent) & 0o077 == 0


def test_umask_cannot_widen_permissions(tmp_path: Path) -> None:
    previous = os.umask(0o000)
    try:
        target = tmp_path / "wide" / "file.txt"
        write_private_bytes(target, b"data")
    finally:
        os.umask(previous)

    assert mode_of(target) == PRIVATE_FILE_MODE
    assert mode_of(target.parent) == PRIVATE_DIR_MODE


def test_existing_files_are_replaced_atomically(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    write_private_bytes(target, b"old content")

    write_private_bytes(target, b"new content")

    assert target.read_bytes() == b"new content"
    assert mode_of(target) == PRIVATE_FILE_MODE
    leftovers = [path for path in tmp_path.iterdir() if path.name != "artifact.json"]
    assert leftovers == [], "no temporary files may remain"


def test_failed_writes_leave_the_old_content_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.json"
    write_private_bytes(target, b"old content")

    def exploding_fsync(_descriptor: int) -> None:
        raise OSError(5, "synthetic fsync failure")

    monkeypatch.setattr(os, "fsync", exploding_fsync)
    with pytest.raises(OSError, match="synthetic fsync failure"):
        write_private_bytes(target, b"half written")
    monkeypatch.undo()

    assert target.read_bytes() == b"old content", "atomic replace must not have happened"
    leftovers = [path for path in tmp_path.iterdir() if path.name != "artifact.json"]
    assert leftovers == [], "the temporary file must be cleaned up"


def test_ensure_private_directory_is_idempotent(tmp_path: Path) -> None:
    directory = tmp_path / "a" / "b"
    ensure_private_directory(directory)
    ensure_private_directory(directory)

    assert mode_of(directory) == PRIVATE_DIR_MODE


def test_preexisting_directories_in_the_controlled_chain_are_repaired(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "out"
    run_directory = output_root / "bid" / "run"
    artifact_dir = run_directory / "security"
    artifact_dir.mkdir(parents=True)
    for path in (output_root, output_root / "bid", run_directory, artifact_dir):
        os.chmod(path, 0o755)

    ensure_private_directory(run_directory, root=output_root)
    write_private_bytes(artifact_dir / "x.json", b"{}", root=run_directory)

    for path in (output_root, output_root / "bid", run_directory, artifact_dir):
        assert mode_of(path) == PRIVATE_DIR_MODE, path
    assert mode_of(artifact_dir / "x.json") == PRIVATE_FILE_MODE


def test_preexisting_target_directory_is_repaired_without_root(tmp_path: Path) -> None:
    directory = tmp_path / "loose"
    directory.mkdir()
    os.chmod(directory, 0o755)

    parent_mode_before = stat.S_IMODE(tmp_path.stat().st_mode)
    ensure_private_directory(directory)

    assert mode_of(directory) == PRIVATE_DIR_MODE
    # The uncontrolled parent (tmp_path) is never touched.
    assert stat.S_IMODE(tmp_path.stat().st_mode) == parent_mode_before


def test_symlinks_in_the_controlled_chain_are_rejected(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    output_root.mkdir()
    (output_root / "bid").symlink_to(elsewhere)

    with pytest.raises(ValueError, match="symlink"):
        ensure_private_directory(output_root / "bid" / "run", root=output_root)


def test_regular_files_in_the_controlled_chain_are_rejected(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    output_root.mkdir()
    (output_root / "bid").write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        ensure_private_directory(output_root / "bid" / "run", root=output_root)


def test_target_outside_the_controlled_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below the controlled root"):
        ensure_private_directory(tmp_path / "a", root=tmp_path / "other-root")
