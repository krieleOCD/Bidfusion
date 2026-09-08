"""M1 regression tests: quarantine root/package ownership hardening.

On platforms exposing ``st_uid``/``os.geteuid``, the quarantine root and
its staging/package directory must be owned by this process's effective
user — a pre-existing, correctly-permissioned (0700), non-symlink
directory owned by someone else must still be rejected fail-closed.
"""

from __future__ import annotations

import io
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bidfusion.bidrun.quarantine import (
    QUARANTINE_ROOT_INVALID,
    QuarantineError,
    QuarantineResult,
    UploadedFileInput,
    _verify_owned_by_current_user,
    quarantine_upload,
)
from bidfusion.schemas.bidrun import AuthorizationRecord, AuthorizationType

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260806-0001"
NOW = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)

_NO_GETEUID = pytest.mark.skipif(not hasattr(os, "geteuid"), reason="platform has no os.geteuid")


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


def upload_one_pdf(root: Path) -> QuarantineResult:
    return quarantine_upload(
        bid_id=BID_ID,
        run_id=RUN_ID,
        authorization=accepted_authorization(),
        files=(UploadedFileInput(filename="a.pdf", stream=io.BytesIO(pdf_bytes())),),
        quarantine_root=root,
        now=NOW,
    )


# --- end-to-end through quarantine_upload -----------------------------------


def test_current_user_owned_root_is_accepted(tmp_path: Path) -> None:
    result = upload_one_pdf(tmp_path / "bidfusion-uploads")
    assert result.package_directory.exists()


@_NO_GETEUID
def test_foreign_owned_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "bidfusion-uploads"
    root.mkdir(mode=0o700)
    real_euid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real_euid + 1)

    with pytest.raises(QuarantineError) as excinfo:
        upload_one_pdf(root)
    assert excinfo.value.error_code == QUARANTINE_ROOT_INVALID


@_NO_GETEUID
def test_foreign_owned_root_error_leaks_no_owner_ids_or_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bidfusion-uploads"
    root.mkdir(mode=0o700)
    real_euid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real_euid + 1)

    with pytest.raises(QuarantineError) as excinfo:
        upload_one_pdf(root)
    message = str(excinfo.value)
    assert str(real_euid) not in message
    assert str(real_euid + 1) not in message
    assert str(root) not in message


def test_ownership_check_does_not_change_symlink_rejection(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlinked_root = tmp_path / "symlinked-root"
    symlinked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(QuarantineError) as excinfo:
        upload_one_pdf(symlinked_root)
    assert excinfo.value.error_code == QUARANTINE_ROOT_INVALID


def test_ownership_check_does_not_change_the_0700_requirement(tmp_path: Path) -> None:
    result = upload_one_pdf(tmp_path / "bidfusion-uploads")
    assert stat.S_IMODE(result.package_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "bidfusion-uploads").stat().st_mode) == 0o700


# --- direct unit tests of the ownership check itself ------------------------


def test_verify_owned_by_current_user_accepts_own_directory(tmp_path: Path) -> None:
    directory = tmp_path / "owned"
    directory.mkdir()
    _verify_owned_by_current_user(directory)  # must not raise


@_NO_GETEUID
def test_verify_owned_by_current_user_rejects_foreign_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "owned"
    directory.mkdir()
    real_euid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real_euid + 1)

    with pytest.raises(QuarantineError) as excinfo:
        _verify_owned_by_current_user(directory)
    assert excinfo.value.error_code == QUARANTINE_ROOT_INVALID


def test_verify_owned_by_current_user_skips_on_platforms_without_geteuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "owned"
    directory.mkdir()
    monkeypatch.delattr(os, "geteuid", raising=False)
    _verify_owned_by_current_user(directory)  # must not raise
