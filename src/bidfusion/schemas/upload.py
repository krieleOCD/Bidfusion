"""Upload quarantine artifacts: one quarantined file and the sealed
manifest that binds a whole uploaded package together.

These contracts describe the *quarantine* trust zone in front of the
existing Security Gate (docs/architecture/level-1-target.md, §3, §8) —
raw, unreviewed bytes that have passed acceptance policy (extension,
detected type, size) but have not been security-cleared. Nothing here
implies ``ALLOW``/``SecurityClearedArtifact`` from
:mod:`bidfusion.schemas.security`; that boundary is untouched and still
owns the only path into parsing and extraction.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference, ArtifactType
from bidfusion.schemas.bidrun import AuthorizationRecord
from bidfusion.schemas.common import BidfusionModel, Sha256Digest
from bidfusion.schemas.ids import BidId, PackageId, RunId


class RetentionPolicy(StrEnum):
    """Closed vocabulary of retention policies a quarantine package can
    declare. Only ``MANUAL_DELETION_REQUIRED`` is ever produced by the
    current slice — no automatic expiry or deletion exists yet."""

    MANUAL_DELETION_REQUIRED = "MANUAL_DELETION_REQUIRED"


class DeletionStatus(StrEnum):
    """Lifecycle of a quarantine package's retained bytes.

    Named in full now so this contract never needs a breaking change
    once deletion is implemented; the current slice only ever produces
    ``ACTIVE`` — no deletion function exists yet.
    """

    ACTIVE = "ACTIVE"
    DELETION_REQUESTED = "DELETION_REQUESTED"
    DELETED = "DELETED"


class QuarantinedUploadFile(BidfusionModel):
    """One raw uploaded file, persisted but not security-cleared.

    ``display_name`` is a sanitized, length-bounded label for humans —
    the original browser filename, cleaned, never used as a filesystem
    path. The file's actual on-disk name is only ever its ``artifact_id``
    (see :attr:`artifact`'s ``content_ref``).
    """

    artifact: ArtifactReference
    display_name: str = Field(min_length=1, max_length=255)
    detected_type: str = Field(min_length=1, description="Content type detected from bytes")
    extension: str = Field(min_length=1, pattern=r"^[a-z0-9]+$")
    size_bytes: int = Field(ge=0)
    sha256: Sha256Digest

    @model_validator(mode="after")
    def _artifact_matches_file(self) -> QuarantinedUploadFile:
        if self.artifact.artifact_type is not ArtifactType.RAW_DOCUMENT:
            msg = "quarantined files must reference raw_document artifacts"
            raise ValueError(msg)
        if self.artifact.content_hash != self.sha256:
            msg = "quarantined file hash must match its artifact reference"
            raise ValueError(msg)
        if self.artifact.content_ref.startswith("/") or ":" in self.artifact.content_ref:
            msg = "quarantined file content_ref must be relative to the package, not absolute"
            raise ValueError(msg)
        return self


class UploadManifest(BidfusionModel):
    """Sealed, versioned record of one quarantined upload package.

    Hash semantics follow :mod:`bidfusion.shared.payloads`: ``artifact``
    is the envelope produced by ``seal_artifact()``, its ``content_hash``
    protects exactly this model's non-envelope fields, and
    ``artifact.input_artifacts`` is the manifest's lineage to every
    quarantined file it describes — never an ID-only reference.
    """

    artifact: ArtifactEnvelope
    package_id: PackageId
    bid_id: BidId
    run_id: RunId
    authorization: AuthorizationRecord
    policy_name: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    files: tuple[QuarantinedUploadFile, ...] = Field(min_length=1)
    total_size_bytes: int = Field(ge=0)
    created_at: datetime
    retention_policy: RetentionPolicy
    retention_policy_version: str = Field(min_length=1)
    expires_at: datetime | None = None
    deletion_status: DeletionStatus
    deletion_requested_at: datetime | None = None
    deleted_at: datetime | None = None

    @model_validator(mode="after")
    def _manifest_is_coherent(self) -> UploadManifest:
        if self.artifact.artifact_type is not ArtifactType.UPLOAD_MANIFEST:
            msg = "upload manifests require an upload_manifest artifact"
            raise ValueError(msg)
        if self.artifact.bid_id != self.bid_id or self.artifact.run_id != self.run_id:
            msg = "the manifest artifact must carry the manifest's own bid_id and run_id"
            raise ValueError(msg)
        if self.artifact.content_ref.startswith("/") or ":" in self.artifact.content_ref:
            msg = "the manifest content_ref must be relative to the package, not absolute"
            raise ValueError(msg)
        self._check_authorization()
        self._check_file_lineage()
        self._check_retention()
        return self

    def _check_authorization(self) -> None:
        if not self.authorization.accepted:
            msg = "an upload manifest can only exist for an accepted authorization"
            raise ValueError(msg)

    def _check_file_lineage(self) -> None:
        file_artifact_ids = [file.artifact.artifact_id for file in self.files]
        if len(file_artifact_ids) != len(set(file_artifact_ids)):
            msg = "manifest files cannot contain duplicate artifact IDs"
            raise ValueError(msg)
        for file in self.files:
            if file.artifact.bid_id != self.bid_id or file.artifact.run_id != self.run_id:
                msg = "every quarantined file must carry the manifest's bid_id and run_id"
                raise ValueError(msg)
        file_artifacts = {file.artifact.artifact_id: file.artifact for file in self.files}
        lineage_artifacts = {
            artifact.artifact_id: artifact for artifact in self.artifact.input_artifacts
        }
        if file_artifacts != lineage_artifacts:
            msg = (
                "the manifest's artifact lineage must reference exactly the "
                "quarantined files it lists — no missing and no extra artifacts"
            )
            raise ValueError(msg)
        if self.total_size_bytes != sum(file.size_bytes for file in self.files):
            msg = "total_size_bytes must equal the sum of every file's size_bytes"
            raise ValueError(msg)

    def _check_retention(self) -> None:
        if (
            self.retention_policy is RetentionPolicy.MANUAL_DELETION_REQUIRED
            and self.expires_at is not None
        ):
            msg = "MANUAL_DELETION_REQUIRED retention cannot carry an automatic expires_at"
            raise ValueError(msg)
        if self.deletion_status is DeletionStatus.ACTIVE:
            if self.deletion_requested_at is not None or self.deleted_at is not None:
                msg = "ACTIVE deletion_status cannot carry deletion timestamps"
                raise ValueError(msg)
        elif self.deletion_status is DeletionStatus.DELETION_REQUESTED:
            if self.deletion_requested_at is None or self.deleted_at is not None:
                msg = "DELETION_REQUESTED requires deletion_requested_at and no deleted_at"
                raise ValueError(msg)
        elif self.deletion_status is DeletionStatus.DELETED:
            if self.deletion_requested_at is None or self.deleted_at is None:
                msg = "DELETED requires both deletion_requested_at and deleted_at"
                raise ValueError(msg)
