"""End-to-end tests for the local walking-skeleton pipeline."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Never

import pytest

import bidfusion.orchestration.local_pipeline as pipeline_module
from bidfusion.document_understanding.canonical import DocumentParsingError
from bidfusion.orchestration import run_package, verify_run_integrity
from bidfusion.orchestration.local_pipeline import main
from bidfusion.orchestration.projection import run_independent_projection
from bidfusion.quality import REVIEW_PACKAGE_NOTICE, ReviewPackage
from bidfusion.schemas import PreflightAssessment, WorkingPackage
from bidfusion.security import DeterministicPreflightScanner

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "synthetic"
BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

DOWNSTREAM_DIRS = (
    "canonical",
    "extraction",
    "normalized",
    "quality",
    "review-package",
    "working-package",
)


class _ExplodingScanner(DeterministicPreflightScanner):
    def assess(self, **_kwargs: object) -> Never:
        raise RuntimeError("synthetic scanner crash")


def run(
    package: str,
    tmp_path: Path,
    *,
    process: bool = True,
    scanner: DeterministicPreflightScanner | None = None,
    output_name: str = "out",
) -> tuple[Path, dict[str, Any]]:
    summary = run_package(
        input_dir=FIXTURES / package,
        output_dir=tmp_path / output_name,
        bid_id=BID_ID,
        process=process,
        now=NOW,
        scanner=scanner,
    )
    payload: dict[str, Any] = json.loads((summary.run_directory / "run-summary.json").read_text())
    return summary.run_directory, payload


def test_clean_package_produces_valid_working_package_json_and_markdown(
    tmp_path: Path,
) -> None:
    run_directory, summary = run("rfp-minimal", tmp_path)

    assert summary["outcome"] == "completed"
    assert summary["package_gate"]["decision"] == "CLEARED"
    assert summary["quality_gate"]["status"] == "ACCEPTABLE"
    assert summary["quality_gate"]["signals"] == []
    assert summary["stages"]["quality_gate"] == {
        "attempted": True,
        "succeeded": True,
        "outcome": "SUCCEEDED",
    }
    assert summary["stages"]["working_package"] == {
        "attempted": True,
        "succeeded": True,
        "outcome": "SUCCEEDED",
    }
    assert all(stage["outcome"] == "SUCCEEDED" for stage in summary["stages"].values())
    assert not (run_directory / "review-package").exists()

    package = WorkingPackage.model_validate(
        json.loads((run_directory / "working-package" / "working-package.audit.json").read_text())
    )
    # v0.2 additionally captures the two label-free MUST submission
    # rows of the formalities sheet
    assert package.requirements_summary.total == 14
    assert len(package.timeline) == 5
    assert len(package.critical_requirements) == 10

    markdown = (run_directory / "working-package" / "working-package.md").read_text()
    assert f"# Bid Working Package — {BID_ID}" in markdown
    assert "COMPLETE (3/3 streams completed)" in markdown
    # PDF page provenance and XLSX sheet/cell provenance reach the final product.
    assert "rfp-invitation.pdf (p. 2)" in markdown
    assert "requirements-matrix.xlsx (Requirements!B2)" in markdown
    assert "The supplier MUST provide a German-speaking service desk." in markdown

    for name in ("DOC-001", "DOC-002", "DOC-003"):
        PreflightAssessment.model_validate(
            json.loads((run_directory / "security" / f"{name}-preflight.json").read_text())
        )


def test_payload_files_are_authoritative_and_manifest_verifies(tmp_path: Path) -> None:
    run_directory, _ = run("rfp-minimal", tmp_path)

    assert verify_run_integrity(run_directory) == ()

    audit_files = sorted(run_directory.rglob("*.audit.json"))
    assert len(audit_files) == 8  # 3 canonical + 3 extraction + dataset + working package
    for audit_file in audit_files:
        audit = json.loads(audit_file.read_text())
        envelope = audit["artifact"]
        payload_path = run_directory / envelope["content_ref"]
        assert payload_path.is_file(), envelope["content_ref"]
        assert sha256(payload_path.read_bytes()).hexdigest() == envelope["content_hash"]


def test_all_run_outputs_are_owner_only(tmp_path: Path) -> None:
    run_directory, _ = run("rfp-minimal", tmp_path)

    for path in sorted(run_directory.rglob("*")):
        mode = path.stat().st_mode & 0o777
        if path.is_dir():
            assert mode == 0o700, path
        else:
            assert mode == 0o600, path
    assert run_directory.stat().st_mode & 0o077 == 0


def test_tampering_with_any_written_file_is_detected(tmp_path: Path) -> None:
    run_directory, _ = run("rfp-minimal", tmp_path)
    audit_file = run_directory / "working-package" / "working-package.audit.json"
    audit_file.write_text(audit_file.read_text() + "\n", encoding="utf-8")
    (run_directory / "extra.txt").write_text("injected", encoding="utf-8")

    issues = verify_run_integrity(run_directory)

    assert "digest mismatch: working-package/working-package.audit.json" in issues
    assert "unlisted file: extra.txt" in issues


def test_without_process_flag_the_pipeline_stops_after_the_gate(tmp_path: Path) -> None:
    run_directory, summary = run("rfp-minimal", tmp_path, process=False)

    assert summary["outcome"] == "security-only"
    assert summary["package_gate"]["decision"] == "CLEARED"
    assert summary["processed"] is False
    assert summary["quality_gate"] is None
    assert summary["stages"]["parsing"] == {
        "attempted": False,
        "succeeded": False,
        "outcome": "NOT_ATTEMPTED",
    }
    for directory in DOWNSTREAM_DIRS:
        assert not (run_directory / directory).exists()
    assert (run_directory / "security" / "package-gate.json").exists()
    assert verify_run_integrity(run_directory) == ()


def test_blocking_finding_stops_the_whole_package_before_any_parser(
    tmp_path: Path,
) -> None:
    run_directory, summary = run("rfp-blocked", tmp_path)

    assert summary["outcome"] == "blocked"
    assert summary["package_gate"]["decision"] == "BLOCKED"
    assert summary["stages"]["package_gate"]["outcome"] == "FAILED"
    assert summary["stages"]["parsing"]["outcome"] == "NOT_ATTEMPTED"
    for directory in DOWNSTREAM_DIRS:
        assert not (run_directory / directory).exists()

    gate = json.loads((run_directory / "security" / "package-gate.json").read_text())
    assert gate["cleared_documents"] == []
    documents = {entry["document_id"]: entry for entry in summary["documents"]}
    clean_cover = documents["DOC-001"]
    assert clean_cover["filename"] == "cover.txt"
    assert clean_cover["verdict"] == "ALLOW"
    assert clean_cover["parse_status"] is None, "clean sibling must not be parsed"


def test_pending_manual_review_produces_no_clearance_and_no_processing(
    tmp_path: Path,
) -> None:
    run_directory, summary = run("rfp-review", tmp_path)

    assert summary["outcome"] == "review-required"
    assert summary["package_gate"]["decision"] == "REVIEW_REQUIRED"
    assert summary["stages"]["package_gate"]["outcome"] == "REVIEW_REQUIRED"
    assert summary["stages"]["package_gate"]["succeeded"] is True
    assert any("MANUAL_REVIEW" in reason for reason in summary["package_gate"]["reasons"])
    gate = json.loads((run_directory / "security" / "package-gate.json").read_text())
    assert gate["cleared_documents"] == []
    for directory in DOWNSTREAM_DIRS:
        assert not (run_directory / directory).exists()


def test_technical_security_failure_fails_closed(tmp_path: Path) -> None:
    run_directory, summary = run("rfp-minimal", tmp_path, scanner=_ExplodingScanner())

    assert summary["outcome"] == "review-required"
    assert summary["package_gate"]["decision"] == "REVIEW_REQUIRED"
    assert summary["stages"]["preflight"] == {
        "attempted": True,
        "succeeded": False,
        "outcome": "FAILED",
    }
    assert any("no security decision" in reason for reason in summary["package_gate"]["reasons"])
    for entry in summary["documents"]:
        assert entry["verdict"] is None
        assert entry["assessment_error"] is not None
    for directory in DOWNSTREAM_DIRS:
        assert not (run_directory / directory).exists()

    inventory = json.loads((run_directory / "inventory" / "inventory.json").read_text())
    assert inventory["documents"] == []
    assert len(inventory["unassessed"]) == 3


def test_textless_pdf_yields_a_review_package_not_a_working_package(
    tmp_path: Path,
) -> None:
    run_directory, summary = run("rfp-unsupported", tmp_path)

    assert summary["package_gate"]["decision"] == "CLEARED"
    assert summary["outcome"] == "review-required"
    assert summary["quality_gate"]["status"] == "REVIEW_REQUIRED"
    # Unsupported content is a review condition, not a technical failure.
    assert summary["stages"]["parsing"] == {
        "attempted": True,
        "succeeded": True,
        "outcome": "REVIEW_REQUIRED",
    }
    documents = {entry["document_id"]: entry for entry in summary["documents"]}
    blank = documents["DOC-001"]
    assert blank["parse_status"] == "UNSUPPORTED"
    assert blank["parse_error_code"] == "PARSER_UNSUPPORTED_CONTENT"
    assert blank["parse_detail"] is not None and "not supported" in blank["parse_detail"]

    assert not (run_directory / "working-package").exists()
    review = ReviewPackage.model_validate(
        json.loads((run_directory / "review-package" / "review-package.json").read_text())
    )
    assert review.notice == REVIEW_PACKAGE_NOTICE
    assert any("was cleared but not processed" in reason for reason in review.reasons)
    assert review.detected_requirements == ()


def test_quality_review_fixture_produces_a_clearly_marked_review_package(
    tmp_path: Path,
) -> None:
    run_directory, summary = run("rfp-quality-review", tmp_path)

    assert summary["package_gate"]["decision"] == "CLEARED"
    assert summary["quality_gate"]["status"] == "REVIEW_REQUIRED"
    assert summary["outcome"] == "review-required"
    # The gate itself executed fine; review is its business outcome.
    assert summary["stages"]["parsing"]["outcome"] == "SUCCEEDED"
    assert summary["stages"]["quality_gate"] == {
        "attempted": True,
        "succeeded": True,
        "outcome": "REVIEW_REQUIRED",
    }
    assert summary["stages"]["working_package"]["outcome"] == "NOT_ATTEMPTED"
    signal_codes = {signal["code"] for signal in summary["quality_gate"]["signals"]}
    assert {
        "parser-warning",
        "empty-page",
        "obligation-without-requirement",
        "unresolved-conflict",
        "stream-empty",
    } <= signal_codes

    assert not (run_directory / "working-package").exists()
    review = ReviewPackage.model_validate(
        json.loads((run_directory / "review-package" / "review-package.json").read_text())
    )
    assert review.notice == REVIEW_PACKAGE_NOTICE
    assert review.quality_gate_name == "bidfusion-mvp-quality-gate"
    assert review.quality_gate_version == "0.4.0"
    assert review.detected_requirements, "detected content must be listed with sources"
    assert all(item.sources for item in review.detected_requirements)
    assert review.unresolved_conflicts
    assert review.required_manual_actions

    markdown = (run_directory / "review-package" / "review-package.md").read_text()
    assert "NOT A COMPLETE BID WORKING PACKAGE" in markdown
    assert "MANUAL REVIEW REQUIRED" in markdown
    assert "mixed-scan.pdf" in markdown
    assert verify_run_integrity(run_directory) == ()


def test_failed_quality_gate_produces_neither_working_nor_review_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def exploding_extractor(*_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("synthetic extractor crash")

    monkeypatch.setattr(pipeline_module, "extract_formalities", exploding_extractor)
    run_directory, summary = run("rfp-minimal", tmp_path)

    assert summary["outcome"] == "failed"
    assert summary["quality_gate"]["status"] == "FAILED"
    assert summary["failed_streams"] == ["FORMALITY"]
    # Technical failure is distinguishable from a review condition.
    assert summary["stages"]["extraction"] == {
        "attempted": True,
        "succeeded": False,
        "outcome": "FAILED",
    }
    assert summary["stages"]["quality_gate"]["outcome"] == "FAILED"
    assert summary["stages"]["quality_gate"]["succeeded"] is True
    assert not (run_directory / "working-package").exists()
    assert not (run_directory / "review-package").exists()
    quality = json.loads((run_directory / "quality" / "quality-gate.json").read_text())
    assert quality["status"] == "FAILED"
    assert summary["processing_run"]["status"] == "FAILED"


def test_rejected_intake_files_keep_the_package_in_review(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "clean.txt").write_text("Synthetic clean note.\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (package_dir / "linked.txt").symlink_to(outside)

    summary = run_package(
        input_dir=package_dir,
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        authorized_non_production_test=True,
        now=NOW,
    )

    assert summary.outcome == "review-required"
    assert summary.exit_code == 2
    assert any("rejected at intake" in reason for reason in summary.gate.reasons)
    inventory = json.loads((summary.run_directory / "inventory" / "inventory.json").read_text())
    assert inventory["rejected_at_intake"] == [
        {"filename": "linked.txt", "reason": "symbolic links are not processed (fail closed)"}
    ]
    for directory in DOWNSTREAM_DIRS:
        assert not (summary.run_directory / directory).exists()


def test_full_processing_outside_synthetic_fixtures_requires_the_override(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "note.txt").write_text("Synthetic local note.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="authorized-non-production-test"):
        run_package(
            input_dir=package_dir,
            output_dir=tmp_path / "out",
            bid_id=BID_ID,
            process=True,
            now=NOW,
        )

    # Security-only runs stay possible without the override.
    summary = run_package(
        input_dir=package_dir,
        output_dir=tmp_path / "out-security",
        bid_id=BID_ID,
        process=False,
        now=NOW,
    )
    assert summary.outcome == "security-only"


def test_override_still_runs_security_and_quality_gates(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "note.txt").write_text("Synthetic local note.\n", encoding="utf-8")

    summary = run_package(
        input_dir=package_dir,
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        authorized_non_production_test=True,
        now=NOW,
    )

    assert summary.gate.decision.value == "CLEARED"
    assert summary.quality is not None, "the quality gate must run despite the override"
    assert summary.quality.status.value == "REVIEW_REQUIRED"  # empty streams
    assert summary.outcome == "review-required"
    assert (summary.run_directory / "review-package" / "review-package.json").exists()


def test_repository_harness_paths_are_blocked_including_descendants_and_symlinks(
    tmp_path: Path,
) -> None:
    fake_repo = tmp_path / "repo"
    (fake_repo / "inbox" / "sub").mkdir(parents=True)
    (fake_repo / "results").mkdir()
    (fake_repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    for bad_input in (
        fake_repo / "inbox",
        fake_repo / "inbox" / "sub",
        fake_repo / "inbox" / ".." / "inbox" / "sub",
    ):
        with pytest.raises(ValueError, match="not permitted"):
            run_package(
                input_dir=bad_input,
                output_dir=tmp_path / "out",
                bid_id=BID_ID,
                process=False,
                now=NOW,
            )

    with pytest.raises(ValueError, match="not permitted"):
        run_package(
            input_dir=tmp_path / "anywhere",
            output_dir=fake_repo / "results" / "deep",
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )

    sneaky_link = tmp_path / "innocent"
    sneaky_link.symlink_to(fake_repo / "inbox" / "sub")
    with pytest.raises(ValueError, match="not permitted"):
        run_package(
            input_dir=sneaky_link,
            output_dir=tmp_path / "out",
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )


def test_outputs_inside_any_repository_checkout_are_blocked(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "note.txt").write_text("synthetic", encoding="utf-8")
    fake_repo = tmp_path / "some-checkout"
    (fake_repo / "data").mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside any repository checkout"):
        run_package(
            input_dir=package_dir,
            output_dir=fake_repo / "data" / "out",
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )


def test_network_access_is_technically_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="network access is disabled"):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
    with pytest.raises(RuntimeError, match="network access is disabled"):
        socket.socket().connect(("192.0.2.1", 80))


def test_repeated_runs_produce_identical_artifacts(tmp_path: Path) -> None:
    first_dir, _ = run("rfp-minimal", tmp_path, output_name="first")
    second_dir, _ = run("rfp-minimal", tmp_path, output_name="second")

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    assert snapshot(first_dir) == snapshot(second_dir)


def test_semantic_repeatability_across_different_clock_values(tmp_path: Path) -> None:
    def run_with_clock(name: str, moment: datetime) -> Path:
        summary = run_package(
            input_dir=FIXTURES / "rfp-minimal",
            output_dir=tmp_path / name,
            bid_id=BID_ID,
            process=True,
            clock=lambda: moment,
        )
        return summary.run_directory

    first = run_with_clock("first", datetime(2026, 8, 4, 12, 0, tzinfo=UTC))
    second = run_with_clock("second", datetime(2026, 8, 5, 9, 30, 15, tzinfo=UTC))

    first_projection = run_independent_projection(first)
    second_projection = run_independent_projection(second)
    assert first_projection == second_projection
    # The authoritative payload files are part of the comparison.
    assert any(name.endswith(".payload.json") for name in first_projection)
    first_manifest = (first / "integrity-manifest.json").read_bytes()
    second_manifest = (second / "integrity-manifest.json").read_bytes()
    assert first_manifest != second_manifest, "run-specific artifacts must still differ"
    assert verify_run_integrity(first) == ()
    assert verify_run_integrity(second) == ()


def test_projection_preserves_business_content_and_masks_only_run_scope(
    tmp_path: Path,
) -> None:
    run_directory, _ = run("rfp-minimal", tmp_path)
    projection = run_independent_projection(run_directory)

    serialized = json.dumps(
        {key: value for key, value in projection.items() if key.endswith(".json")}
    )
    # Business deadlines, quotes, and counts survive untouched.
    assert "2026-09-30" in serialized, "extracted deadline dates must be preserved"
    assert "German-speaking service desk" in serialized
    # Run-scoped fields are masked.
    assert "RUN-NORM" in serialized
    assert "TS-NORM" in serialized
    summary = projection["run-summary.json"]
    assert summary["run_id"] == "RUN-NORM"
    assert summary["started_at"] == "TS-NORM"
    # The rendered Markdown keeps the business deadline table rows.
    markdown = projection["working-package/working-package.md"]
    assert "| 2026-09-30 17:00 | SUBMISSION |" in markdown
    assert "- Generated: TS-NORM" in markdown


def test_run_summary_reports_real_timestamps_from_the_injected_clock(
    tmp_path: Path,
) -> None:
    ticks = [
        datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 4, 12, 0, 7, tzinfo=UTC),
    ]
    summary = run_package(
        input_dir=FIXTURES / "rfp-minimal",
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        clock=lambda: ticks.pop(0),
    )

    payload = json.loads((summary.run_directory / "run-summary.json").read_text())
    assert payload["started_at"] == "2026-08-04T12:00:00+00:00"
    assert payload["completed_at"] == "2026-08-04T12:00:07+00:00"
    processing_run = payload["processing_run"]
    assert processing_run["started_at"] != processing_run["completed_at"]


def test_input_and_output_directories_must_be_distinct(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "a.txt").write_text("synthetic", encoding="utf-8")

    with pytest.raises(ValueError, match="must be different"):
        run_package(
            input_dir=package,
            output_dir=package,
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )
    with pytest.raises(ValueError, match="not be nested"):
        run_package(
            input_dir=package,
            output_dir=package / "out",
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )


class _LeakyParser:
    """Parser whose exception text carries simulated secrets and RFP content."""

    parser_name = "leaky-parser"
    parser_version = "0.0.1"

    def parse(self, **_kwargs: object) -> Never:
        raise DocumentParsingError(
            "password=SUPERSECRET-XYZ; source quote: "
            "'Der Bieter muss 42 Server in Frankfurt liefern'"
        )


def test_parser_exception_texts_never_reach_persisted_outputs(tmp_path: Path) -> None:
    summary = run_package(
        input_dir=FIXTURES / "rfp-minimal",
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        now=NOW,
        parser_registry=lambda _file_type: _LeakyParser(),
    )

    for path in sorted(summary.run_directory.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        assert b"SUPERSECRET-XYZ" not in content, path
        assert b"Der Bieter" not in content, path

    payload = json.loads((summary.run_directory / "run-summary.json").read_text())
    for entry in payload["documents"]:
        assert entry["parse_error_code"] == "PARSER_TECHNICAL_FAILURE"
        assert "SUPERSECRET" not in (entry["parse_detail"] or "")
    assert payload["stages"]["parsing"] == {
        "attempted": True,
        "succeeded": False,
        "outcome": "FAILED",
    }
    assert summary.outcome == "review-required"


class _SecretCodeError(DocumentParsingError):
    """Parser error whose *code attribute* itself carries hostile content."""

    error_code = "password=TOPSECRET-CODE; Der Bieter zahlt 1M"


class _LeakyCodeParser:
    parser_name = "leaky-code-parser"
    parser_version = "0.0.1"

    def parse(self, **_kwargs: object) -> Never:
        raise _SecretCodeError("quote: 'Der Bieter zahlt 1M pro Jahr' password=TOPSECRET-CODE")


def test_unknown_error_codes_collapse_to_the_generic_allowlisted_code(
    tmp_path: Path,
) -> None:
    summary = run_package(
        input_dir=FIXTURES / "rfp-minimal",
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        now=NOW,
        parser_registry=lambda _file_type: _LeakyCodeParser(),
    )

    for path in sorted(summary.run_directory.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        assert b"TOPSECRET-CODE" not in content, path
        assert b"Der Bieter" not in content, path

    payload = json.loads((summary.run_directory / "run-summary.json").read_text())
    for entry in payload["documents"]:
        assert entry["parse_error_code"] == "GENERIC_PARSER_FAILURE"
        assert "TOPSECRET" not in (entry["parse_detail"] or "")


def test_markdown_projection_touches_only_controlled_metadata_lines() -> None:
    from bidfusion.orchestration.projection import _normalize_markdown

    text = "\n".join(
        [
            "# Bid Working Package — BID-2026-000123",
            "- Generated: 2026-08-04T12:00:00+00:00",
            "- Run: RUN-20260804-120000000000",
            "- Source dataset: ART-20260804-120000000000000010",
            "Der Text erwähnt RUN-20260101-000001 und ART-20260101-000000000001 frei.",
            "| 2026-09-30 17:00 | SUBMISSION | Angebotsabgabe | rfp.pdf (p. 1) |",
        ]
    )

    normalized = _normalize_markdown(text)

    assert "- Generated: TS-NORM" in normalized
    assert "- Run: RUN-NORM" in normalized
    assert "- Source dataset: ART-NORM" in normalized
    # Free document text and business rows stay verbatim.
    assert "RUN-20260101-000001" in normalized
    assert "ART-20260101-000000000001" in normalized
    assert "| 2026-09-30 17:00 | SUBMISSION | Angebotsabgabe | rfp.pdf (p. 1) |" in normalized


def test_preexisting_world_readable_output_directories_are_repaired(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    run_id = "RUN-20260804-120000000000"  # run_id_for(NOW)
    artifact_dir = out / BID_ID / run_id / "security"
    artifact_dir.mkdir(parents=True)
    for path in (out, out / BID_ID, out / BID_ID / run_id, artifact_dir):
        os.chmod(path, 0o755)

    run_directory, _ = run("rfp-minimal", tmp_path)

    assert run_directory == (out / BID_ID / run_id).resolve()
    for path in (out, out / BID_ID, run_directory, *sorted(run_directory.rglob("*"))):
        mode = path.stat().st_mode & 0o777
        expected = 0o700 if path.is_dir() else 0o600
        assert mode == expected, path


def test_cli_requires_explicit_directories_and_reports_exit_codes(tmp_path: Path) -> None:
    clean_exit = main(
        [
            "--input",
            str(FIXTURES / "rfp-minimal"),
            "--output",
            str(tmp_path / "cli-out"),
            "--bid-id",
            BID_ID,
            "--process",
        ]
    )
    review_exit = main(
        [
            "--input",
            str(FIXTURES / "rfp-quality-review"),
            "--output",
            str(tmp_path / "cli-out-review"),
            "--bid-id",
            BID_ID,
            "--process",
        ]
    )

    assert clean_exit == 0
    assert review_exit == 2
    produced = list((tmp_path / "cli-out" / BID_ID).glob("*/working-package/working-package.md"))
    assert len(produced) == 1
    review_produced = list(
        (tmp_path / "cli-out-review" / BID_ID).glob("*/review-package/review-package.md")
    )
    assert len(review_produced) == 1

    with pytest.raises(SystemExit):
        main(["--input", str(FIXTURES / "rfp-minimal")])


def test_cli_reports_unusable_output_directories_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("not a directory", encoding="utf-8")

    exit_code = main(
        [
            "--input",
            str(FIXTURES / "rfp-minimal"),
            "--output",
            str(blocker / "out"),
            "--bid-id",
            BID_ID,
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "bidfusion-run:" in captured.err
    assert "Traceback" not in captured.err
