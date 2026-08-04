"""Filesystem tests for the local inbox-to-results preflight runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bidfusion.security.local_runner import LocalPreflightStatus, main, run_inbox

RUN_AT = datetime(2026, 8, 4, 12, 30, 45, tzinfo=UTC)
CLEAN_PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


def test_runner_scans_nested_inbox_and_writes_assessments_and_summary(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    results = tmp_path / "results"
    nested = inbox / "package-a"
    nested.mkdir(parents=True)
    clean_file = nested / "request.pdf"
    unknown_file = inbox / "payload.bin"
    clean_file.write_bytes(CLEAN_PDF)
    unknown_file.write_bytes(b"\x00\x01unknown")

    summary = run_inbox(
        inbox=inbox,
        results=results,
        bid_id="BID-2026-000123",
        now=RUN_AT,
    )

    assert summary.run_id == "RUN-20260804-123045000000"
    assert summary.passed == 1
    assert summary.requires_attention == 1
    assert summary.errors == 0
    assert tuple(result.filename for result in summary.files) == (
        "package-a/request.pdf",
        "payload.bin",
    )
    assert clean_file.read_bytes() == CLEAN_PDF
    assert unknown_file.exists()

    assessment_files = sorted(results.glob("*.preflight.json"))
    assert len(assessment_files) == 2
    clean_payload: dict[str, object] = json.loads(assessment_files[0].read_text())
    assert "verdict" not in clean_payload
    assert "allows_processing" not in clean_payload
    assert clean_payload["document_id"] == "DOC-001"

    summary_payload: dict[str, object] = json.loads(summary.summary_file.read_text())
    assert summary_payload["scope"] == "deterministic_preflight_only"
    assert summary_payload["files_total"] == 2
    assert summary_payload["passed_preflight"] == 1
    assert summary_payload["requires_attention"] == 1
    assert (results / "latest-summary.json").exists()


def test_runner_does_not_copy_document_content_into_results(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    results = tmp_path / "results"
    inbox.mkdir()
    marker = "SYNTHETIC-RFP-CONTENT-MUST-NOT-BE-COPIED"
    (inbox / "dummy.txt").write_text(marker, encoding="utf-8")

    run_inbox(
        inbox=inbox,
        results=results,
        bid_id="BID-2026-000123",
        now=RUN_AT,
    )

    combined_results = "\n".join(path.read_text() for path in results.glob("*.json"))
    assert marker not in combined_results


def test_runner_ignores_hidden_files_and_symlinks(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    results = tmp_path / "results"
    inbox.mkdir()
    (inbox / ".gitkeep").touch()
    source = tmp_path / "outside.pdf"
    source.write_bytes(CLEAN_PDF)
    (inbox / "linked.pdf").symlink_to(source)

    summary = run_inbox(
        inbox=inbox,
        results=results,
        bid_id="BID-2026-000123",
        now=RUN_AT,
    )

    assert summary.files == ()
    assert summary.passed == 0
    assert summary.summary_file.exists()


def test_runner_rejects_results_directory_below_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"

    with pytest.raises(ValueError, match="must not be the inbox"):
        run_inbox(
            inbox=inbox,
            results=inbox / "results",
            bid_id="BID-2026-000123",
            now=RUN_AT,
        )


def test_cli_exit_code_distinguishes_clean_and_attention_runs(tmp_path: Path) -> None:
    clean_inbox = tmp_path / "clean-inbox"
    attention_inbox = tmp_path / "attention-inbox"
    clean_inbox.mkdir()
    attention_inbox.mkdir()
    (clean_inbox / "request.pdf").write_bytes(CLEAN_PDF)
    (attention_inbox / "unknown.bin").write_bytes(b"\x00unknown")

    clean_code = main(
        [
            "--inbox",
            str(clean_inbox),
            "--results",
            str(tmp_path / "clean-results"),
            "--bid-id",
            "BID-2026-000123",
        ]
    )
    attention_code = main(
        [
            "--inbox",
            str(attention_inbox),
            "--results",
            str(tmp_path / "attention-results"),
            "--bid-id",
            "BID-2026-000123",
        ]
    )

    assert clean_code == 0
    assert attention_code == 2
    attention_summary = json.loads(
        (tmp_path / "attention-results" / "latest-summary.json").read_text()
    )
    assert attention_summary["files"][0]["preflight_status"] == LocalPreflightStatus.ATTENTION
