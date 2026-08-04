"""Local inbox-to-results runner for deterministic Security Gate testing."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from bidfusion.schemas.artifact import ArtifactReference, ArtifactType
from bidfusion.security.preflight import DeterministicPreflightScanner, PreflightConfig


class LocalPreflightStatus(StrEnum):
    """Local harness status; deliberately not a Security Gate verdict."""

    PASS = "PASS"
    ATTENTION = "ATTENTION"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class LocalFileResult:
    """Summary entry for one inbox file."""

    filename: str
    document_id: str
    artifact_id: str
    status: LocalPreflightStatus
    assessment_file: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "document_id": self.document_id,
            "artifact_id": self.artifact_id,
            "preflight_status": self.status.value,
            "assessment_file": self.assessment_file,
        }


@dataclass(frozen=True, slots=True)
class LocalRunSummary:
    """Serializable summary for one local inbox run."""

    run_id: str
    bid_id: str
    started_at: datetime
    files: tuple[LocalFileResult, ...]
    summary_file: Path

    @property
    def passed(self) -> int:
        return sum(result.status is LocalPreflightStatus.PASS for result in self.files)

    @property
    def requires_attention(self) -> int:
        return sum(result.status is LocalPreflightStatus.ATTENTION for result in self.files)

    @property
    def errors(self) -> int:
        return sum(result.status is LocalPreflightStatus.ERROR for result in self.files)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "bid_id": self.bid_id,
            "started_at": self.started_at.isoformat(),
            "scope": "deterministic_preflight_only",
            "files_total": len(self.files),
            "passed_preflight": self.passed,
            "requires_attention": self.requires_attention,
            "errors": self.errors,
            "files": [result.as_dict() for result in self.files],
        }


def run_inbox(
    *,
    inbox: Path,
    results: Path,
    bid_id: str,
    now: datetime | None = None,
    config: PreflightConfig | None = None,
) -> LocalRunSummary:
    """Assess every non-hidden regular file below ``inbox`` and write JSON results."""
    inbox_root = inbox.resolve()
    results_root = results.resolve()
    if inbox_root == results_root or inbox_root in results_root.parents:
        msg = "results directory must not be the inbox or a directory below it"
        raise ValueError(msg)

    inbox_root.mkdir(parents=True, exist_ok=True)
    results_root.mkdir(parents=True, exist_ok=True)

    started_at = now or datetime.now(UTC)
    run_id = started_at.strftime("RUN-%Y%m%d-%H%M%S%f")
    date_stamp = started_at.strftime("%Y%m%d")
    time_stamp = started_at.strftime("%H%M%S%f")
    scanner = DeterministicPreflightScanner(config=config)
    input_files = _input_files(inbox_root)
    file_results: list[LocalFileResult] = []

    for index, input_path in enumerate(input_files, start=1):
        if index > 999_999:
            msg = "local preflight supports at most 999999 files per run"
            raise ValueError(msg)

        document_id = f"DOC-{index:03d}"
        artifact_id = f"ART-{date_stamp}-{time_stamp}{index:06d}"
        relative_name = input_path.relative_to(inbox_root).as_posix()

        try:
            content = input_path.read_bytes()
            artifact = ArtifactReference(
                artifact_id=artifact_id,
                bid_id=bid_id,
                run_id=run_id,
                artifact_type=ArtifactType.RAW_DOCUMENT,
                schema_version="1.0.0",
                content_ref=f"inbox/{relative_name}",
                content_hash=sha256(content).hexdigest(),
            )
            assessment = scanner.assess(
                artifact=artifact,
                document_id=document_id,
                filename=input_path.name,
                content=content,
                assessed_at=started_at,
            )
            assessment_name = f"{run_id}_{artifact_id}.preflight.json"
            _write_json(results_root / assessment_name, assessment.model_dump(mode="json"))
            status = (
                LocalPreflightStatus.PASS
                if assessment.completed_successfully
                else LocalPreflightStatus.ATTENTION
            )
            file_results.append(
                LocalFileResult(
                    filename=relative_name,
                    document_id=document_id,
                    artifact_id=artifact_id,
                    status=status,
                    assessment_file=assessment_name,
                )
            )
        except (OSError, ValueError):
            file_results.append(
                LocalFileResult(
                    filename=relative_name,
                    document_id=document_id,
                    artifact_id=artifact_id,
                    status=LocalPreflightStatus.ERROR,
                    assessment_file=None,
                )
            )

    summary_path = results_root / f"{run_id}.summary.json"
    summary = LocalRunSummary(
        run_id=run_id,
        bid_id=bid_id,
        started_at=started_at,
        files=tuple(file_results),
        summary_file=summary_path,
    )
    _write_json(summary_path, summary.as_dict())
    _write_json(results_root / "latest-summary.json", summary.as_dict())
    return summary


def _input_files(inbox: Path) -> tuple[Path, ...]:
    files = (
        path
        for path in inbox.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not any(part.startswith(".") for part in path.relative_to(inbox).parts)
    )
    return tuple(sorted(files, key=lambda path: path.relative_to(inbox).as_posix()))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the local test-runner command line interface."""
    parser = argparse.ArgumentParser(
        prog="bidfusion-preflight",
        description="Run deterministic BidFusion preflight for every file in a local inbox.",
    )
    parser.add_argument("--inbox", type=Path, default=Path("inbox"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--bid-id", default=None)
    parser.add_argument("--max-file-size-mb", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    started_at = datetime.now(UTC)
    bid_id = args.bid_id or f"BID-{started_at.year}-000001"
    if args.max_file_size_mb <= 0:
        build_parser().error("--max-file-size-mb must be positive")

    summary = run_inbox(
        inbox=args.inbox,
        results=args.results,
        bid_id=bid_id,
        now=started_at,
        config=PreflightConfig(max_file_size_bytes=args.max_file_size_mb * 1024 * 1024),
    )
    print(
        f"Preflight complete: {len(summary.files)} file(s), "
        f"{summary.passed} passed, {summary.requires_attention} attention, "
        f"{summary.errors} error(s)."
    )
    print(f"Summary: {summary.summary_file}")
    return 0 if summary.requires_attention == 0 and summary.errors == 0 else 2


def cli() -> None:
    """Installed console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
