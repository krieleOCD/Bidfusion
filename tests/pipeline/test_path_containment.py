"""Containment tests for input trust, bid IDs, and the final run path (C1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bidfusion.orchestration import run_package
from bidfusion.shared.identifiers import validate_bid_id
from bidfusion.shared.pathguards import (
    is_trusted_synthetic_input,
    trusted_synthetic_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "synthetic"
BID_ID = "BID-2026-000123"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_trusted_synthetic_root_is_the_repository_fixture_directory() -> None:
    trusted = trusted_synthetic_root()
    assert trusted == FIXTURES.resolve()
    assert is_trusted_synthetic_input((FIXTURES / "rfp-minimal").resolve())


def test_external_fixtures_synthetic_lookalike_is_not_trusted(tmp_path: Path) -> None:
    lookalike = tmp_path / "fixtures" / "synthetic" / "customer-rfp"
    lookalike.mkdir(parents=True)
    (lookalike / "note.txt").write_text("external data\n", encoding="utf-8")

    assert not is_trusted_synthetic_input(lookalike.resolve())
    with pytest.raises(ValueError, match="authorized-non-production-test"):
        run_package(
            input_dir=lookalike,
            output_dir=tmp_path / "out",
            bid_id=BID_ID,
            process=True,
            now=NOW,
        )
    assert not (tmp_path / "out").exists(), "nothing may be written"


def test_symlinked_input_resolving_outside_the_trusted_root_needs_override(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external-package"
    external.mkdir()
    (external / "note.txt").write_text("external\n", encoding="utf-8")
    link = tmp_path / "fixtures" / "synthetic"
    link.parent.mkdir()
    link.symlink_to(external)

    with pytest.raises(ValueError, match="authorized-non-production-test"):
        run_package(
            input_dir=link,
            output_dir=tmp_path / "out",
            bid_id=BID_ID,
            process=True,
            now=NOW,
        )


def test_symlinked_input_resolving_into_the_trusted_root_is_processed(
    tmp_path: Path,
) -> None:
    link = tmp_path / "shortcut"
    link.symlink_to(FIXTURES / "rfp-minimal")

    summary = run_package(
        input_dir=link,
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
        now=NOW,
    )
    assert summary.outcome == "completed"


@pytest.mark.parametrize(
    "bad_bid_id",
    [
        "/tmp/evil",
        "\\\\evil\\share",
        "../escape",
        "..",
        ".",
        "a/b",
        "a\\b",
        "BID-2026-000123/../../escape",
        "BID-26-1",
        "bid-2026-000123",
        "",
    ],
)
def test_invalid_bid_ids_are_rejected_before_any_write(tmp_path: Path, bad_bid_id: str) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()  # deliberately empty: an empty package writes nothing

    with pytest.raises(ValueError, match="bid ID"):
        validate_bid_id(bad_bid_id)
    with pytest.raises(ValueError, match="bid ID"):
        run_package(
            input_dir=package_dir,
            output_dir=tmp_path / "out",
            bid_id=bad_bid_id,
            process=False,
            now=NOW,
        )
    assert not (tmp_path / "out").exists(), "nothing may be written"


def test_empty_package_with_valid_bid_id_writes_only_below_output_root(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    summary = run_package(
        input_dir=package_dir,
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=False,
        now=NOW,
    )

    assert summary.run_directory.is_relative_to((tmp_path / "out").resolve())
    payload = json.loads((summary.run_directory / "run-summary.json").read_text())
    assert payload["bid_id"] == BID_ID


def test_symlinked_bid_directory_cannot_move_the_run_path_outside_output_root(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / BID_ID).symlink_to(elsewhere)

    with pytest.raises(ValueError, match="below the output directory"):
        run_package(
            input_dir=FIXTURES / "rfp-minimal",
            output_dir=out,
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )
    assert list(elsewhere.iterdir()) == [], "nothing may be written outside output root"


def test_symlinked_output_root_into_a_repository_checkout_is_rejected(
    tmp_path: Path,
) -> None:
    fake_repo = tmp_path / "checkout"
    (fake_repo / "data").mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    link = tmp_path / "harmless-out"
    link.symlink_to(fake_repo / "data")

    with pytest.raises(ValueError, match="outside any repository checkout"):
        run_package(
            input_dir=FIXTURES / "rfp-minimal",
            output_dir=link,
            bid_id=BID_ID,
            process=False,
            now=NOW,
        )
