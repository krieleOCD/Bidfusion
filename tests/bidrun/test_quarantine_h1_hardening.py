"""H1 regression tests: the read path trusts the authoritative sealed
payload, never the derived audit JSON, for content or content_hash.

Scenario labels (A-E) match the governing hardening instructions:

A. audit-only content tampering is never rendered
B. audit-only hash tampering is never rendered
C. tampered payload without a correct reseal -> INTEGRITY_FAILURE
D. tampered payload with an inconsistent reseal -> INTEGRITY_FAILURE
E. missing/malformed audit JSON -> INTEGRITY_FAILURE (documented choice)

Every scenario "regenerates the package integrity manifest" first (a
careful attacker who keeps whole-file digests self-consistent), so
these tests specifically exercise the sealed-artifact check
(:func:`bidfusion.shared.payloads.verify_sealed_artifact`) — not just
the coarser whole-file :func:`bidfusion.orchestration.verify_run_integrity`
check, which a naive attacker would already trip.
"""

from __future__ import annotations

import io
import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from bidfusion.bidrun.quarantine import (
    INTEGRITY_FAILURE,
    QuarantineError,
    QuarantineResult,
    UploadedFileInput,
    quarantine_upload,
    read_quarantine_package,
)
from bidfusion.orchestration import verify_run_integrity
from bidfusion.schemas.bidrun import AuthorizationRecord, AuthorizationType
from bidfusion.shared.secure_io import PRIVATE_FILE_MODE

JsonDocument = dict[str, Any]

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260806-0001"
NOW = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)


def accepted_authorization() -> AuthorizationRecord:
    return AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=True,
        accepted_at=NOW,
        scope="non-production-internal-test",
        policy_version="1.0.0",
    )


def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%synthetic\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


def quarantine_one_pdf(tmp_path: Path, filename: str = "invitation.pdf") -> QuarantineResult:
    return quarantine_upload(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=accepted_authorization(),
        files=(UploadedFileInput(filename=filename, stream=io.BytesIO(pdf_bytes())),),
        quarantine_root=tmp_path / "bidfusion-uploads",
        now=NOW,
    )


def _load_json(path: Path) -> JsonDocument:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_json(path: Path, document: JsonDocument) -> None:
    _write_bytes(path, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode())


def _write_bytes(path: Path, data: bytes) -> None:
    """Overwrite a 0600 file's bytes, then restore its owner-only mode."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else PRIVATE_FILE_MODE
    if path.exists():
        os.chmod(path, 0o600)
    path.write_bytes(data)
    os.chmod(path, mode)


def _tamper_content_only(path: Path, mutate: Callable[[JsonDocument], None]) -> None:
    """Mutate only the non-``artifact`` top-level keys of a sealed audit
    JSON — the portion :func:`read_quarantine_package` must ignore. The
    envelope (``artifact``) sub-object is popped out and restored
    byte-for-byte unchanged, so a test can never accidentally also forge
    the envelope while trying to forge "just the content"."""
    document = _load_json(path)
    envelope = document.pop("artifact")
    mutate(document)
    document["artifact"] = envelope
    _write_json(path, document)


def _regenerate_integrity_manifest(
    package_directory: Path, *, remove: tuple[str, ...] = ()
) -> None:
    """Recompute every tracked file's digest and drop any removed entries.

    Simulates a careful attacker who keeps ``integrity-manifest.json``
    self-consistent with whatever bytes are actually on disk, so these
    tests exercise the *sealed-artifact* check specifically.
    """
    integrity_path = package_directory / "integrity-manifest.json"
    manifest = _load_json(integrity_path)
    for relative in remove:
        manifest["files"].pop(relative, None)
    for relative in list(manifest["files"]):
        path = package_directory / relative
        if path.is_file():
            manifest["files"][relative] = sha256(path.read_bytes()).hexdigest()
        else:
            manifest["files"].pop(relative, None)
    _write_json(integrity_path, manifest)


# --- A: audit-only content tampering is never rendered ---------------------


def test_a_audit_only_display_name_tampering_is_ignored(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"

    def forge_display_name(document: JsonDocument) -> None:
        document["files"][0]["display_name"] = "forged-name.pdf"

    _tamper_content_only(manifest_audit_path, forge_display_name)
    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    reread = read_quarantine_package(result.package_directory)
    assert reread.manifest.files[0].display_name == "invitation.pdf"
    assert "forged-name.pdf" not in reread.manifest.model_dump_json()


def test_a_audit_only_bidrun_state_tampering_is_ignored(tmp_path: Path) -> None:
    from bidfusion.schemas.bidrun import BidRunState

    result = quarantine_one_pdf(tmp_path)
    record_audit_path = result.package_directory / "bidrun" / "bidrun-record.audit.json"

    def forge_state(document: JsonDocument) -> None:
        document["bid_run"]["current_state"] = "CLEARED"

    _tamper_content_only(record_audit_path, forge_state)
    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    reread = read_quarantine_package(result.package_directory)
    assert reread.bid_run.current_state is BidRunState.QUARANTINED


# --- B: audit-only hash tampering is never rendered -------------------------


def test_b_audit_only_file_hash_tampering_is_ignored(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    true_sha256 = result.manifest.files[0].sha256
    forged_sha256 = ("f" * 64) if true_sha256 != "f" * 64 else ("e" * 64)
    file_artifact_id = result.manifest.files[0].artifact.artifact_id

    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"

    def forge_manifest_hash(document: JsonDocument) -> None:
        document["files"][0]["sha256"] = forged_sha256
        document["files"][0]["artifact"]["content_hash"] = forged_sha256

    _tamper_content_only(manifest_audit_path, forge_manifest_hash)

    record_audit_path = result.package_directory / "bidrun" / "bidrun-record.audit.json"

    def forge_record_hashes(document: JsonDocument) -> None:
        for ref in document["bid_run"]["artifact_refs"]:
            if ref["artifact_id"] == file_artifact_id:
                ref["content_hash"] = forged_sha256

    _tamper_content_only(record_audit_path, forge_record_hashes)

    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    reread = read_quarantine_package(result.package_directory)
    assert reread.manifest.files[0].sha256 == true_sha256
    assert forged_sha256 not in reread.manifest.model_dump_json()
    assert forged_sha256 not in reread.bid_run.model_dump_json()


# --- C: tampered payload without a correct reseal ---------------------------


def test_c_tampered_payload_without_reseal_is_rejected(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    payload_path = result.package_directory / "manifest" / "upload-manifest.payload.json"
    original = payload_path.read_bytes()
    tampered = original.replace(b"invitation.pdf", b"forged-name.pdf")
    assert tampered != original
    _write_bytes(payload_path, tampered)

    # Regenerate the integrity manifest (whole-file digests now agree with
    # the tampered payload) but never touch audit.json's content_hash
    # claim, which still reflects the true, original payload.
    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


# --- D: tampered payload with an inconsistent reseal ------------------------


def test_d_tampered_payload_with_inconsistent_reseal_is_rejected(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    payload_path = result.package_directory / "manifest" / "upload-manifest.payload.json"
    tampered_payload = payload_path.read_bytes().replace(b"invitation.pdf", b"forged-name.pdf")
    _write_bytes(payload_path, tampered_payload)

    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"
    document = _load_json(manifest_audit_path)
    # "Inconsistently" reseal: pick an arbitrary wrong hash, not the
    # correctly recomputed one, for the envelope's content_hash claim.
    document["artifact"]["content_hash"] = "1" * 64
    document["files"][0]["display_name"] = "forged-name.pdf"
    _write_json(manifest_audit_path, document)

    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


# --- E: missing/malformed audit JSON — documented choice: fail closed ------


def test_e_missing_audit_json_fails_closed(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"
    manifest_audit_path.unlink()
    _regenerate_integrity_manifest(
        result.package_directory, remove=("manifest/upload-manifest.audit.json",)
    )
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_e_malformed_audit_json_fails_closed(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"
    _write_bytes(manifest_audit_path, b"not even json")
    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_e_audit_json_missing_artifact_key_fails_closed(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    manifest_audit_path = result.package_directory / "manifest" / "upload-manifest.audit.json"
    document = _load_json(manifest_audit_path)
    del document["artifact"]
    _write_json(manifest_audit_path, document)
    _regenerate_integrity_manifest(result.package_directory)
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


# --- baseline: an ordinary, untampered package still reads cleanly --------


def test_ordinary_untampered_package_reads_successfully(tmp_path: Path) -> None:
    result = quarantine_one_pdf(tmp_path)
    reread = read_quarantine_package(result.package_directory)
    assert reread.manifest.files[0].display_name == "invitation.pdf"
    assert reread.bid_run == result.bid_run
