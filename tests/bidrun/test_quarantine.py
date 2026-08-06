"""Upload quarantine service: acceptance, security hardening, and lineage.

Numbered comments below correspond to the governing instructions' test
list (A: acceptance, B: path/filename, C: type/size policy, D:
state/lineage, E: negative downstream guarantees, F: filesystem/privacy).
"""

from __future__ import annotations

import io
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

import bidfusion.orchestration as orchestration
from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY, UploadPolicy
from bidfusion.bidrun.quarantine import (
    DUPLICATE_DISPLAY_NAME,
    EMPTY_PACKAGE,
    EXTENSION_NOT_ALLOWED,
    FILE_TOO_LARGE,
    INVALID_FILENAME,
    MACRO_CONTENT_DETECTED,
    PACKAGE_TOO_LARGE,
    QUARANTINE_ROOT_INVALID,
    TOO_MANY_FILES,
    TYPE_MISMATCH,
    QuarantineError,
    QuarantineResult,
    UploadedFileInput,
    quarantine_upload,
)
from bidfusion.orchestration import verify_run_integrity
from bidfusion.schemas.bidrun import AuthorizationRecord, AuthorizationType, BidRunState
from bidfusion.shared.identifiers import ArtifactIdAllocator
from bidfusion.shared.secure_io import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260805-0001"
NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]


def accepted_authorization() -> AuthorizationRecord:
    return AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=True,
        accepted_at=NOW,
        scope="non-production-internal-test",
        policy_version="1.0.0",
    )


def upload(filename: str, content: bytes) -> UploadedFileInput:
    return UploadedFileInput(filename=filename, stream=io.BytesIO(content))


def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%synthetic\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


def xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "Requirement"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def txt_bytes() -> bytes:
    return b"Synthetic RFP notes.\nLine two.\n"


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def docx_like_bytes() -> bytes:
    return zip_bytes({"word/document.xml": b"<document/>", "[Content_Types].xml": b"<Types/>"})


def xlsm_like_bytes() -> bytes:
    return zip_bytes({"xl/workbook.xml": b"<workbook/>", "xl/vbaProject.bin": b"\x00\x01macro"})


def generic_zip_bytes() -> bytes:
    return zip_bytes({"readme.txt": b"hello"})


def quarantine(
    tmp_path: Path,
    files: tuple[UploadedFileInput, ...],
    *,
    root: Path | None = None,
    now: datetime = NOW,
    policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
    authorization: AuthorizationRecord | None = None,
) -> QuarantineResult:
    return quarantine_upload(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=authorization if authorization is not None else accepted_authorization(),
        files=files,
        quarantine_root=root if root is not None else tmp_path / "bidfusion-uploads",
        now=now,
        policy=policy,
    )


# --- A. Upload acceptance -------------------------------------------------


def test_a1_valid_single_pdf(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("invitation.pdf", pdf_bytes()),))
    assert result.bid_run.current_state is BidRunState.QUARANTINED
    assert result.manifest.files[0].extension == "pdf"


def test_a2_valid_xlsx(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("matrix.xlsx", xlsx_bytes()),))
    assert result.manifest.files[0].detected_type.endswith("spreadsheetml.sheet")


def test_a3_valid_txt(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("notes.txt", txt_bytes()),))
    assert result.manifest.files[0].extension == "txt"


def test_a4_valid_mixed_package(tmp_path: Path) -> None:
    result = quarantine(
        tmp_path,
        (
            upload("invitation.pdf", pdf_bytes()),
            upload("matrix.xlsx", xlsx_bytes()),
            upload("notes.txt", txt_bytes()),
        ),
    )
    assert len(result.manifest.files) == 3
    assert result.bid_run.current_state is BidRunState.QUARANTINED


def test_a5_authorization_not_accepted_is_refused(tmp_path: Path) -> None:
    unaccepted = AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=False,
        accepted_at=None,
        scope="non-production-internal-test",
        policy_version="1.0.0",
    )
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("a.txt", txt_bytes()),), authorization=unaccepted)
    assert excinfo.value.error_code == "AUTHORIZATION_NOT_ACCEPTED"


# A6 (POST/Redirect/GET) belongs to the Flask application layer (Schritt 4);
# this slice has no HTTP surface to test it against yet.


# --- B. Path and filename security ----------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.pdf",
        "/etc/passwd.pdf",
        "a/b.pdf",
        "a\\b.pdf",
        "C:\\evil.pdf",
        "",
        ".",
        "...",
        "a\x00b.pdf",
        "a\u202eb.pdf",  # RTL override (format character)
        "a\x07b.pdf",  # bell control character
    ],
)
def test_b_rejects_dangerous_filenames(tmp_path: Path, filename: str) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload(filename, pdf_bytes()),))
    assert excinfo.value.error_code == INVALID_FILENAME


def test_b_rejects_duplicate_normalized_display_names(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(
            tmp_path,
            (upload("report.pdf", pdf_bytes()), upload("report.pdf", pdf_bytes())),
        )
    assert excinfo.value.error_code == DUPLICATE_DISPLAY_NAME


def test_b_does_not_overwrite_an_existing_package_directory(tmp_path: Path) -> None:
    root = tmp_path / "bidfusion-uploads"
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=root, now=NOW)
    # Force a second attempt to collide on the same package_id (same `now`).
    (result.package_directory / "tamper-marker.txt").write_bytes(b"x")
    with pytest.raises(QuarantineError):
        quarantine(tmp_path, (upload("b.pdf", pdf_bytes()),), root=root, now=NOW)
    # The original package is untouched by the failed second attempt.
    assert (result.package_directory / "tamper-marker.txt").read_bytes() == b"x"


def test_b_symlinked_root_is_rejected(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlinked_root = tmp_path / "symlinked-root"
    symlinked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=symlinked_root)
    assert excinfo.value.error_code == QUARANTINE_ROOT_INVALID


def test_b_symlinked_package_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bidfusion-uploads"
    root.mkdir(mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / ".staging").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(QuarantineError):
        quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=root)


def test_b_final_path_stays_inside_quarantine_root(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    root = (tmp_path / "bidfusion-uploads").resolve()
    assert result.package_directory.resolve().is_relative_to(root)


# --- C. Type and size policy ------------------------------------------------


def test_c_extension_content_mismatch_is_rejected(tmp_path: Path) -> None:
    # Named .xlsx but the content is a DOCX-shaped ZIP.
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("fake.xlsx", docx_like_bytes()),))
    assert excinfo.value.error_code == TYPE_MISMATCH


def test_c_docx_is_rejected_by_extension(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("proposal.docx", docx_like_bytes()),))
    assert excinfo.value.error_code == EXTENSION_NOT_ALLOWED


def test_c_xlsm_is_rejected_by_extension(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("macro.xlsm", xlsm_like_bytes()),))
    assert excinfo.value.error_code == EXTENSION_NOT_ALLOWED


def test_c_macro_enabled_workbook_disguised_as_xlsx_is_rejected(tmp_path: Path) -> None:
    # xl/workbook.xml alone would misdetect as XLSX; the macro entry must
    # still be caught even though extension and container shape "match".
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("macro.xlsx", xlsm_like_bytes()),))
    assert excinfo.value.error_code == MACRO_CONTENT_DETECTED


def test_c_generic_zip_named_xlsx_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("plain.xlsx", generic_zip_bytes()),))
    assert excinfo.value.error_code == TYPE_MISMATCH


def test_c_generic_zip_is_rejected_by_extension(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("archive.zip", generic_zip_bytes()),))
    assert excinfo.value.error_code == EXTENSION_NOT_ALLOWED


def test_c_executable_or_script_is_rejected(tmp_path: Path) -> None:
    for filename in ("malware.exe", "script.sh", "payload.js"):
        with pytest.raises(QuarantineError) as excinfo:
            quarantine(tmp_path, (upload(filename, b"MZ\x90\x00"),))
        assert excinfo.value.error_code == EXTENSION_NOT_ALLOWED


def test_c_file_over_the_size_limit_is_rejected(tmp_path: Path) -> None:
    oversized = b"a" * (DEFAULT_UPLOAD_POLICY.max_file_size_bytes + 1)
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("big.txt", oversized),))
    assert excinfo.value.error_code == FILE_TOO_LARGE


def test_c_package_over_the_total_size_limit_is_rejected(tmp_path: Path) -> None:
    policy = UploadPolicy(
        policy_name="test-policy",
        policy_version="0.1.0",
        max_file_size_bytes=30,
        max_package_size_bytes=50,
        max_files_per_package=10,
        allowed_extensions=frozenset({"txt"}),
        allowed_mime_types_by_extension={"txt": frozenset({"text/plain"})},
    )
    files = tuple(upload(f"f{i}.txt", b"a" * 30) for i in range(3))
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, files, policy=policy)
    assert excinfo.value.error_code == PACKAGE_TOO_LARGE


def test_c_bounded_read_aborts_early_without_consuming_the_whole_stream() -> None:
    from bidfusion.bidrun.quarantine import _read_bounded_stream

    class _CountingStream:
        def __init__(self, total: int) -> None:
            self._remaining = total
            self.read_calls = 0

        def read(self, size: int = -1) -> bytes:
            self.read_calls += 1
            amount = min(size if size and size > 0 else self._remaining, self._remaining)
            self._remaining -= amount
            return b"a" * amount if amount else b""

    huge_stream = _CountingStream(500 * 1024 * 1024)  # 500 MiB declared
    limit = 25 * 1024 * 1024  # 25 MiB
    with pytest.raises(QuarantineError) as excinfo:
        _read_bounded_stream(huge_stream, limit)
    assert excinfo.value.error_code == FILE_TOO_LARGE
    # Aborted a couple of chunks past the limit, not after reading 500 MiB.
    assert huge_stream.read_calls <= (limit // (1024 * 1024)) + 2


def test_c_too_many_files_and_the_limit_boundary(tmp_path: Path) -> None:
    twenty = tuple(upload(f"f{i:02d}.txt", txt_bytes()) for i in range(20))
    result = quarantine(tmp_path, twenty, root=tmp_path / "ok")
    assert len(result.manifest.files) == 20

    twenty_one = tuple(upload(f"f{i:02d}.txt", txt_bytes()) for i in range(21))
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, twenty_one, root=tmp_path / "too-many")
    assert excinfo.value.error_code == TOO_MANY_FILES


def test_c_empty_package_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, ())
    assert excinfo.value.error_code == EMPTY_PACKAGE


# --- D. State and lineage --------------------------------------------------


def test_d_exact_bid_run_artifact_lineage(tmp_path: Path) -> None:
    result = quarantine(
        tmp_path,
        (upload("a.pdf", pdf_bytes()), upload("b.txt", txt_bytes())),
    )
    assert result.bid_run.bid_id == BID_ID
    assert result.bid_run.run_id == RUN_ID
    assert result.manifest.bid_id == BID_ID
    assert result.manifest.run_id == RUN_ID
    for file in result.manifest.files:
        assert file.artifact.bid_id == BID_ID
        assert file.artifact.run_id == RUN_ID
    assert result.bid_run.source_package_artifact == result.manifest.artifact.as_reference()
    assert set(result.bid_run.artifact_refs) == {
        result.manifest.artifact.as_reference(),
        *(file.artifact for file in result.manifest.files),
    }


def test_d_duplicate_artifact_id_across_files_never_reaches_a_valid_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken allocator (every ID the same) must never produce a
    silently-accepted manifest — the contract's own duplicate-ID
    invariant (tests/unit/test_upload_schemas.py) must stop it, and the
    service must translate that into a safe ``QuarantineError``."""

    def always_the_same_id(self: object) -> str:
        return "ART-20260805-000001"

    monkeypatch.setattr(ArtifactIdAllocator, "allocate", always_the_same_id)
    with pytest.raises(QuarantineError):
        quarantine(
            tmp_path,
            (upload("a.pdf", pdf_bytes()), upload("b.txt", txt_bytes())),
        )


def test_d_bidrun_ends_exactly_in_quarantined(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    assert result.bid_run.current_state is BidRunState.QUARANTINED
    assert [t.to_state for t in result.bid_run.state_history] == [
        BidRunState.UPLOADED,
        BidRunState.QUARANTINED,
    ]


def test_d_tampered_file_is_detected_by_integrity_verification(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    assert verify_run_integrity(result.package_directory) == ()

    tampered_file = result.package_directory / result.manifest.files[0].artifact.content_ref
    original_mode = tampered_file.stat().st_mode
    os.chmod(tampered_file, 0o600)
    tampered_file.write_bytes(b"tampered bytes")
    os.chmod(tampered_file, stat.S_IMODE(original_mode))

    issues = verify_run_integrity(result.package_directory)
    assert issues != ()


def test_d_manifest_tampering_is_detected_by_integrity_verification(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    manifest_path = result.package_directory / "manifest" / "upload-manifest.payload.json"
    original = manifest_path.read_bytes()
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(original + b"\ntampered")

    issues = verify_run_integrity(result.package_directory)
    assert issues != ()


# --- E. Negative downstream guarantees --------------------------------------


def test_e_run_package_is_never_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding_run_package(**_kwargs: object) -> None:
        raise AssertionError("run_package must never be called by quarantine")

    monkeypatch.setattr(orchestration, "run_package", exploding_run_package)
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    assert result.bid_run.current_state is BidRunState.QUARANTINED


def test_e_no_parser_extractor_or_security_module_is_imported() -> None:
    import ast

    import bidfusion.bidrun.quarantine as quarantine_module

    forbidden_prefixes = (
        "bidfusion.document_understanding",
        "bidfusion.extraction",
        "bidfusion.normalization",
        "bidfusion.quality",
        "bidfusion.working_package",
        "bidfusion.security",
    )
    assert quarantine_module.__file__ is not None
    with open(quarantine_module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        for prefix in forbidden_prefixes:
            assert not module_name.startswith(prefix), module_name


# --- F. Filesystem and privacy ----------------------------------------------


def test_f_all_directories_are_0700_and_files_are_0600(tmp_path: Path) -> None:
    result = quarantine(
        tmp_path,
        (upload("a.pdf", pdf_bytes()), upload("b.xlsx", xlsx_bytes())),
    )
    for path in result.package_directory.rglob("*"):
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_dir():
            assert mode == PRIVATE_DIR_MODE, path.name
        else:
            assert mode == PRIVATE_FILE_MODE, path.name
    assert stat.S_IMODE(result.package_directory.lstat().st_mode) == PRIVATE_DIR_MODE


def test_f_manifest_contains_no_absolute_local_paths(tmp_path: Path) -> None:
    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    serialized = result.manifest.model_dump_json()
    assert str(tmp_path) not in serialized
    assert str(result.package_directory) not in serialized
    for file in result.manifest.files:
        assert not file.artifact.content_ref.startswith("/")
    assert not result.manifest.artifact.content_ref.startswith("/")


def test_f_exceptions_never_leak_paths_or_content(tmp_path: Path) -> None:
    root = REPO_ROOT / "fixtures" / "synthetic"  # a real path inside the repo
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=root)
    assert str(root) not in str(excinfo.value)
    assert "synthetic" not in str(excinfo.value)


def test_f_quarantine_root_inside_the_repository_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError) as excinfo:
        quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=REPO_ROOT / "tmp-quarantine")
    assert excinfo.value.error_code == QUARANTINE_ROOT_INVALID


# --- G. Rollback / atomicity -------------------------------------------------


def test_g_a_failed_upload_leaves_no_visible_package(tmp_path: Path) -> None:
    root = tmp_path / "bidfusion-uploads"
    with pytest.raises(QuarantineError):
        quarantine(
            tmp_path,
            (upload("a.pdf", pdf_bytes()), upload("a.pdf", pdf_bytes())),
            root=root,
        )
    if root.exists():
        visible_entries = [entry for entry in root.iterdir() if entry.name != ".staging"]
        assert visible_entries == []
        staging = root / ".staging"
        if staging.exists():
            assert list(staging.iterdir()) == []


def test_g_failure_partway_through_writing_cleans_up_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bidfusion.bidrun import quarantine as quarantine_module

    root = tmp_path / "bidfusion-uploads"
    original_write_json = quarantine_module._StagingWriter.write_json

    def exploding_write_json(self: object, relative: str, payload: dict[str, object]) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(quarantine_module._StagingWriter, "write_json", exploding_write_json)
    with pytest.raises(QuarantineError):
        quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),), root=root)
    monkeypatch.setattr(quarantine_module._StagingWriter, "write_json", original_write_json)

    if root.exists():
        visible_entries = [entry for entry in root.iterdir() if entry.name != ".staging"]
        assert visible_entries == []


# --- H. read_quarantine_package: the persisted, re-verified truth ----------


def test_h_read_quarantine_package_round_trips(tmp_path: Path) -> None:
    from bidfusion.bidrun.quarantine import read_quarantine_package

    result = quarantine(
        tmp_path,
        (upload("a.pdf", pdf_bytes()), upload("b.xlsx", xlsx_bytes())),
    )
    reread = read_quarantine_package(result.package_directory)
    assert reread.bid_run == result.bid_run
    assert reread.manifest == result.manifest
    assert reread.package_directory == result.package_directory


def test_h_read_quarantine_package_detects_a_tampered_file(tmp_path: Path) -> None:
    from bidfusion.bidrun.quarantine import INTEGRITY_FAILURE, read_quarantine_package

    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    tampered_file = result.package_directory / result.manifest.files[0].artifact.content_ref
    os.chmod(tampered_file, 0o600)
    tampered_file.write_bytes(b"tampered bytes")
    os.chmod(tampered_file, stat.S_IMODE(tampered_file.stat().st_mode))

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_h_read_quarantine_package_detects_a_tampered_manifest(tmp_path: Path) -> None:
    from bidfusion.bidrun.quarantine import INTEGRITY_FAILURE, read_quarantine_package

    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    manifest_path = result.package_directory / "manifest" / "upload-manifest.audit.json"
    original = manifest_path.read_bytes()
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(original.replace(b"pdf", b"xyz"))

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_h_read_quarantine_package_detects_a_tampered_bidrun_record(tmp_path: Path) -> None:
    from bidfusion.bidrun.quarantine import INTEGRITY_FAILURE, read_quarantine_package

    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    record_path = result.package_directory / "bidrun" / "bidrun-record.audit.json"
    original = record_path.read_bytes()
    os.chmod(record_path, 0o600)
    record_path.write_bytes(original.replace(b"QUARANTINED", b"CLEARED"))

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_h_read_quarantine_package_rejects_a_missing_directory(tmp_path: Path) -> None:
    from bidfusion.bidrun.quarantine import INTEGRITY_FAILURE, read_quarantine_package

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(tmp_path / "does-not-exist")
    assert excinfo.value.error_code == INTEGRITY_FAILURE


def test_h_read_quarantine_package_rejects_internally_consistent_but_wrong_lineage(
    tmp_path: Path,
) -> None:
    """A record whose hash *is* correctly re-signed (an attacker who
    updates the integrity manifest too) must still be caught — by the
    semantic lineage cross-check against the manifest, not just the
    whole-file digest check."""
    import json
    from hashlib import sha256

    from bidfusion.bidrun.quarantine import INTEGRITY_FAILURE, read_quarantine_package

    result = quarantine(tmp_path, (upload("a.pdf", pdf_bytes()),))
    record_path = result.package_directory / "bidrun" / "bidrun-record.audit.json"
    manifest_hash = result.manifest.artifact.content_hash
    forged_hash = ("f" * 64) if manifest_hash != "f" * 64 else ("e" * 64)

    original = record_path.read_bytes()
    tampered = original.replace(manifest_hash.encode(), forged_hash.encode())
    assert tampered != original  # the fixture actually contains the hash

    os.chmod(record_path, 0o600)
    record_path.write_bytes(tampered)
    os.chmod(record_path, PRIVATE_FILE_MODE)

    integrity_path = result.package_directory / "integrity-manifest.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    integrity["files"]["bidrun/bidrun-record.audit.json"] = sha256(tampered).hexdigest()
    os.chmod(integrity_path, 0o600)
    integrity_path.write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(integrity_path, PRIVATE_FILE_MODE)

    # The whole-file digest check now passes (it was "correctly" re-signed).
    assert verify_run_integrity(result.package_directory) == ()

    with pytest.raises(QuarantineError) as excinfo:
        read_quarantine_package(result.package_directory)
    assert excinfo.value.error_code == INTEGRITY_FAILURE
