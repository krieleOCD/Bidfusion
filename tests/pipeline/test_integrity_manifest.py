"""Regression tests for verify_run_integrity()'s hardened manifest parsing (L1).

A syntactically valid but structurally malformed integrity manifest must
never raise ``AttributeError`` or otherwise crash — every malformed shape
is rejected fail-closed with a stable, non-empty issues tuple. This
function is shared by the pipeline and by
:func:`bidfusion.bidrun.quarantine.read_quarantine_package`, so hardening
it once covers both callers.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from bidfusion.orchestration import verify_run_integrity
from bidfusion.orchestration.local_pipeline import (
    MANIFEST_FILENAME,
    _parsed_integrity_entries,
)


def _write_manifest(run_directory: Path, content: object) -> None:
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / MANIFEST_FILENAME).write_text(json.dumps(content), encoding="utf-8")


# --- integration: through verify_run_integrity on real files ---------------


def test_malformed_top_level_list_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, ["not", "a", "mapping"])
    assert verify_run_integrity(tmp_path) != ()


def test_malformed_top_level_scalar_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "just a string")
    assert verify_run_integrity(tmp_path) != ()


def test_missing_files_key_is_treated_as_empty_and_flags_real_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    _write_manifest(tmp_path, {"hash_convention": "x"})
    issues = verify_run_integrity(tmp_path)
    assert any("unlisted file" in issue for issue in issues)


def test_files_as_a_list_is_rejected_not_a_crash(tmp_path: Path) -> None:
    # The originally reported bug: {"files": []} used to raise AttributeError
    # because list.items() does not exist.
    _write_manifest(tmp_path, {"files": []})
    try:
        issues = verify_run_integrity(tmp_path)
    except AttributeError:
        pytest.fail("verify_run_integrity raised AttributeError on a malformed manifest")
    assert issues != ()


def test_non_string_digest_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a.txt": 12345}})
    assert verify_run_integrity(tmp_path) != ()


def test_invalid_sha256_format_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a.txt": "not-a-valid-hash"}})
    assert verify_run_integrity(tmp_path) != ()


def test_short_sha256_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a.txt": "abc123"}})
    assert verify_run_integrity(tmp_path) != ()


def test_uppercase_sha256_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a.txt": "A" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"/etc/passwd": "a" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_traversal_path_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"../escape.txt": "a" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_embedded_traversal_segment_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a/../../escape.txt": "a" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_windows_separator_path_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a\\b.txt": "a" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_duplicate_normalized_path_is_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, {"files": {"a.txt": "a" * 64, "./a.txt": "b" * 64}})
    assert verify_run_integrity(tmp_path) != ()


def test_unknown_extra_top_level_key_is_tolerated(tmp_path: Path) -> None:
    content = b"hello"
    (tmp_path / "a.txt").write_bytes(content)
    digest = sha256(content).hexdigest()
    _write_manifest(
        tmp_path,
        {"hash_convention": "x", "unexpected_field": 123, "files": {"a.txt": digest}},
    )
    assert verify_run_integrity(tmp_path) == ()


def test_unreadable_json_is_rejected_not_a_crash(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / MANIFEST_FILENAME).write_text("{not valid json", encoding="utf-8")
    assert verify_run_integrity(tmp_path) != ()


# --- direct unit tests of the private parser for JSON-inexpressible shapes --


def test_parsed_integrity_entries_rejects_non_dict_top_level() -> None:
    assert _parsed_integrity_entries(["a", "b"]) is None
    assert _parsed_integrity_entries("scalar") is None
    assert _parsed_integrity_entries(None) is None


def test_parsed_integrity_entries_rejects_non_string_path_key() -> None:
    # Not producible via json.loads (JSON object keys are always strings),
    # but the parser itself must not trust its caller either way.
    assert _parsed_integrity_entries({"files": {123: "a" * 64}}) is None


def test_parsed_integrity_entries_accepts_a_well_formed_manifest() -> None:
    digest = "a" * 64
    assert _parsed_integrity_entries({"files": {"a.txt": digest}}) == {"a.txt": digest}
