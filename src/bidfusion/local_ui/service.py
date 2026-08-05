"""Application service of the local UI: trusted fixture packages and runs.

Presentation-side orchestration only: this module enumerates the one
trusted ``fixtures/synthetic/`` root (via the central path guards) and
starts pipeline runs exclusively through the existing
:func:`bidfusion.orchestration.run_package` API. It never reads
document contents itself and contains no security-, parsing-,
extraction-, or quality logic.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bidfusion.orchestration import PipelineRunSummary, run_package
from bidfusion.shared.pathguards import trusted_synthetic_root
from bidfusion.shared.secure_io import ensure_private_directory


class UnknownPackageError(LookupError):
    """A package name does not match any trusted synthetic fixture package."""


class PipelineExecutionError(RuntimeError):
    """The pipeline refused or could not finish a run.

    The message is a static, operator-safe text; details stay in the
    run artifacts and are never echoed into UI responses.
    """


OPERATOR_SAFE_RUN_MESSAGE = (
    "The pipeline rejected or could not finish this run. No results are available for it."
)


@dataclass(frozen=True, slots=True)
class PackageFile:
    """Display metadata of one file inside a synthetic fixture package."""

    name: str
    file_type: str


@dataclass(frozen=True, slots=True)
class SyntheticPackage:
    """One selectable synthetic RFP fixture package."""

    name: str
    files: tuple[PackageFile, ...]

    @property
    def document_count(self) -> int:
        return len(self.files)


def list_packages() -> tuple[SyntheticPackage, ...]:
    """All trusted synthetic fixture packages, sorted by name.

    Only directory and file names are read — never file contents. An
    absent synthetic root yields an empty tuple.
    """
    root = trusted_synthetic_root()
    if root is None:
        return ()
    packages: list[SyntheticPackage] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        files = tuple(
            PackageFile(name=path.name, file_type=_file_type(path))
            for path in sorted(entry.rglob("*"))
            if path.is_file() and not path.name.startswith(".")
        )
        packages.append(SyntheticPackage(name=entry.name, files=files))
    return tuple(packages)


def package_input_dir(name: str) -> Path:
    """Resolve a trusted package name to its fixture directory.

    The name must exactly match one offered package; anything else —
    unknown names, separators, dot segments, file names — is rejected
    before any path is built from it.
    """
    root = trusted_synthetic_root()
    if root is None or name not in {package.name for package in list_packages()}:
        raise UnknownPackageError("unknown synthetic package")
    return root / name


def start_run(
    package_name: str,
    *,
    process: bool,
    output_base: Path | None = None,
    now: datetime | None = None,
) -> tuple[PipelineRunSummary, Path]:
    """Run the existing pipeline on one trusted synthetic package.

    Every execution gets a fresh private (0700) output root outside the
    repository checkout — by default below the system temporary
    directory, or below ``output_base`` when one is configured (tests).
    The pipeline itself validates all directories again and writes all
    artifacts through its secure output abstraction.
    """
    input_dir = package_input_dir(package_name)
    output_root = _new_output_root(output_base)
    started = now if now is not None else datetime.now(UTC)
    try:
        summary = run_package(
            input_dir=input_dir,
            output_dir=output_root,
            bid_id=f"BID-{started.year}-000001",
            process=process,
            now=now,
        )
    except (OSError, ValueError) as failure:
        raise PipelineExecutionError(OPERATOR_SAFE_RUN_MESSAGE) from failure
    return summary, output_root


def _new_output_root(output_base: Path | None) -> Path:
    if output_base is not None:
        ensure_private_directory(output_base)
        return Path(tempfile.mkdtemp(prefix="bidfusion-ui-", dir=output_base))
    return Path(tempfile.mkdtemp(prefix="bidfusion-ui-"))


def _file_type(path: Path) -> str:
    suffix = path.suffix.removeprefix(".")
    return suffix.upper() if suffix else "FILE"
