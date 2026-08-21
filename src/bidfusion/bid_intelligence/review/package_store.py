"""Append-only local persistence for Reviewed Working Packages.

Reviewed packages are bid/run-side artifacts. Like the review records,
they are stored under one private root *beside* the pipeline run
directory — never inside it, because the run's integrity manifest is
sealed at pipeline time and must keep verifying; and never under the
golden knowledge store, because a reviewed package is not golden
knowledge.

Layout under the root::

    reviewed-working-package-v0001.payload.json
    reviewed-working-package-v0001.audit.json
    reviewed-working-package-v0002.payload.json
    ...

Following the project hash convention
(:mod:`bidfusion.shared.payloads`), the ``.payload.json`` file holds the
canonical payload bytes the envelope hash binds to, and the
``.audit.json`` file holds the complete model including the envelope.
Loading reconstructs the model from the audit file and then verifies it
against the payload file: the sealed content hash must match the model,
and the stored payload bytes must equal the model's canonical bytes.
Any deviation — an edited decision, a removed review, a changed
evidence reference, corrupt JSON, a stray or symlinked file, a filename
that disagrees with its content — refuses the whole load rather than
rendering a tampered package as valid.

Every filename is derived from the validated ``package_version`` field
only; no request-controlled value ever shapes a path. Writes are atomic
and private via :mod:`bidfusion.shared.secure_io`, and an existing
version is never overwritten.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bidfusion.bid_intelligence.review.package import (
    REVIEWED_PACKAGE_DOMAIN,
    ReviewedWorkingPackage,
)
from bidfusion.shared.payloads import artifact_payload_bytes, verify_sealed_artifact
from bidfusion.shared.secure_io import ensure_private_directory, write_private_bytes

_PACKAGE_FILE = re.compile(r"^reviewed-working-package-v(\d{4})\.(payload|audit)\.json$")

#: Static, content-free failure texts. Never interpolate package content,
#: identifiers, or paths into them.
_CONFLICT_MESSAGE = "a reviewed package with this version already exists and is never overwritten"
_INTEGRITY_MESSAGE = "the stored reviewed packages could not be validated"


class PackageStoreConflictError(RuntimeError):
    """An existing reviewed package version would have been overwritten."""


class PackageStoreIntegrityError(RuntimeError):
    """Stored reviewed packages are inconsistent; the load is refused."""


def _payload_name(version: int) -> str:
    return f"reviewed-working-package-v{version:04d}.payload.json"


def _audit_name(version: int) -> str:
    return f"reviewed-working-package-v{version:04d}.audit.json"


class ReviewedPackageStore:
    """Read/append reviewed packages below one private local root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def next_version(self) -> int:
        """The next free package version; validates the store first."""
        packages = self.read_packages()
        return 1 + max((package.package_version for package in packages), default=0)

    def append_package(self, package: ReviewedWorkingPackage) -> None:
        """Persist one new package version atomically; never overwrite."""
        payload_name = _payload_name(package.package_version)
        if package.artifact.content_ref != payload_name:
            raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE)
        verify_sealed_artifact(package, domain=REVIEWED_PACKAGE_DOMAIN)
        ensure_private_directory(self._root)
        payload_path = self._root / payload_name
        audit_path = self._root / _audit_name(package.package_version)
        if payload_path.exists() or audit_path.exists():
            raise PackageStoreConflictError(_CONFLICT_MESSAGE)
        write_private_bytes(
            payload_path,
            artifact_payload_bytes(package, domain=REVIEWED_PACKAGE_DOMAIN),
            root=self._root,
        )
        write_private_bytes(
            audit_path,
            (json.dumps(package.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
            root=self._root,
        )

    def read_packages(self) -> tuple[ReviewedWorkingPackage, ...]:
        """Every stored package, fully verified, in version order.

        An absent root is an empty store. Any unexpected file, symlink,
        unparseable record, broken seal, or payload/audit disagreement
        fails the whole load closed.
        """
        if not self._root.is_dir():
            return ()
        versions: dict[int, dict[str, Path]] = {}
        for path in sorted(self._root.iterdir()):
            match = _PACKAGE_FILE.match(path.name)
            if match is None or path.is_symlink() or not path.is_file():
                raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE)
            versions.setdefault(int(match.group(1)), {})[match.group(2)] = path
        packages: list[ReviewedWorkingPackage] = []
        for version in sorted(versions):
            pair = versions[version]
            if set(pair) != {"payload", "audit"}:
                raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE)
            packages.append(self._read_verified(version, pair["payload"], pair["audit"]))
        return tuple(packages)

    def read_latest(self) -> ReviewedWorkingPackage | None:
        """The highest stored package version, fully verified, or ``None``."""
        packages = self.read_packages()
        return packages[-1] if packages else None

    def _read_verified(
        self, version: int, payload_path: Path, audit_path: Path
    ) -> ReviewedWorkingPackage:
        try:
            package = ReviewedWorkingPackage.model_validate_json(
                audit_path.read_text(encoding="utf-8")
            )
        except ValueError as failure:
            raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE) from failure
        if package.package_version != version or package.artifact.content_ref != _payload_name(
            version
        ):
            raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE)
        try:
            verify_sealed_artifact(package, domain=REVIEWED_PACKAGE_DOMAIN)
        except ValueError as failure:
            raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE) from failure
        if payload_path.read_bytes() != artifact_payload_bytes(
            package, domain=REVIEWED_PACKAGE_DOMAIN
        ):
            raise PackageStoreIntegrityError(_INTEGRITY_MESSAGE)
        return package
