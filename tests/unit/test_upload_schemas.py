"""QuarantinedUploadFile / UploadManifest contract invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bidfusion.schemas import (
    ArtifactEnvelope,
    ArtifactProducer,
    ArtifactReference,
    ArtifactType,
    AuthorizationRecord,
    AuthorizationType,
    DeletionStatus,
    QuarantinedUploadFile,
    RetentionPolicy,
    UploadManifest,
)

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260805-0001"
PACKAGE_ID = "PKG-20260805-0001"
FILE_ARTIFACT_ID = "ART-20260805-000001"
MANIFEST_ARTIFACT_ID = "ART-20260805-000002"
HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)


def raw_artifact(
    *,
    artifact_id: str = FILE_ARTIFACT_ID,
    bid_id: str = BID_ID,
    run_id: str = RUN_ID,
    content_hash: str = HASH_A,
    content_ref: str = f"files/{FILE_ARTIFACT_ID}.pdf",
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=artifact_id,
        bid_id=bid_id,
        run_id=run_id,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref=content_ref,
        content_hash=content_hash,
    )


def quarantined_file(
    *,
    artifact: ArtifactReference | None = None,
    sha256: str = HASH_A,
) -> QuarantinedUploadFile:
    return QuarantinedUploadFile(
        artifact=artifact if artifact is not None else raw_artifact(content_hash=sha256),
        display_name="rfp-invitation.pdf",
        detected_type="application/pdf",
        extension="pdf",
        size_bytes=1234,
        sha256=sha256,
    )


def authorization() -> AuthorizationRecord:
    return AuthorizationRecord(
        authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
        accepted=True,
        accepted_at=NOW,
        scope="non-production-internal-test",
        policy_version="1.0.0",
    )


def manifest(**overrides: object) -> UploadManifest:
    file = quarantined_file()
    envelope = ArtifactEnvelope(
        artifact_id=MANIFEST_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.UPLOAD_MANIFEST,
        schema_version="1.0.0",
        content_ref="manifest/upload-manifest.payload.json",
        content_hash=HASH_B,
        producer=ArtifactProducer(component="bidfusion-quarantine-service", version="0.1.0"),
        input_artifacts=(file.artifact,),
        created_at=NOW,
    )
    fields: dict[str, object] = {
        "artifact": envelope,
        "package_id": PACKAGE_ID,
        "bid_id": BID_ID,
        "run_id": RUN_ID,
        "authorization": authorization(),
        "policy_name": "bidfusion-upload-policy",
        "policy_version": "0.1.0",
        "files": (file,),
        "total_size_bytes": file.size_bytes,
        "created_at": NOW,
        "retention_policy": RetentionPolicy.MANUAL_DELETION_REQUIRED,
        "retention_policy_version": "0.1.0",
        "expires_at": None,
        "deletion_status": DeletionStatus.ACTIVE,
        "deletion_requested_at": None,
        "deleted_at": None,
    }
    fields.update(overrides)
    return UploadManifest(**fields)  # type: ignore[arg-type]


# --- QuarantinedUploadFile ------------------------------------------------


def test_quarantined_file_requires_matching_hash() -> None:
    with pytest.raises(ValidationError, match="must match its artifact reference"):
        QuarantinedUploadFile(
            artifact=raw_artifact(content_hash=HASH_A),
            display_name="a.pdf",
            detected_type="application/pdf",
            extension="pdf",
            size_bytes=1,
            sha256=HASH_B,
        )


def test_quarantined_file_rejects_non_raw_document_artifact() -> None:
    with pytest.raises(ValidationError, match="raw_document artifacts"):
        QuarantinedUploadFile(
            artifact=raw_artifact().model_copy(
                update={"artifact_type": ArtifactType.WORKING_PACKAGE}
            ),
            display_name="a.pdf",
            detected_type="application/pdf",
            extension="pdf",
            size_bytes=1,
            sha256=HASH_A,
        )


def test_quarantined_file_rejects_absolute_content_ref() -> None:
    with pytest.raises(ValidationError, match="relative to the package"):
        QuarantinedUploadFile(
            artifact=raw_artifact(content_ref="/etc/passwd"),
            display_name="a.pdf",
            detected_type="application/pdf",
            extension="pdf",
            size_bytes=1,
            sha256=HASH_A,
        )


# --- UploadManifest ---------------------------------------------------------


def test_manifest_builds_with_a_coherent_single_file() -> None:
    built = manifest()
    assert built.package_id == PACKAGE_ID
    assert built.files[0].artifact.artifact_id == FILE_ARTIFACT_ID
    assert built.deletion_status is DeletionStatus.ACTIVE
    assert built.retention_policy is RetentionPolicy.MANUAL_DELETION_REQUIRED
    assert built.expires_at is None


def test_manifest_requires_upload_manifest_artifact_type() -> None:
    with pytest.raises(ValidationError, match="upload_manifest artifact"):
        manifest(
            artifact=ArtifactEnvelope(
                artifact_id=MANIFEST_ARTIFACT_ID,
                bid_id=BID_ID,
                run_id=RUN_ID,
                artifact_type=ArtifactType.WORKING_PACKAGE,
                schema_version="1.0.0",
                content_ref="manifest/upload-manifest.payload.json",
                content_hash=HASH_B,
                producer=ArtifactProducer(component="c", version="0.1.0"),
                input_artifacts=(raw_artifact(),),
                created_at=NOW,
            )
        )


def test_manifest_rejects_unaccepted_authorization() -> None:
    with pytest.raises(ValidationError, match="accepted authorization"):
        manifest(
            authorization=AuthorizationRecord(
                authorization_type=AuthorizationType.NON_PRODUCTION_TEST_CONFIRMATION,
                accepted=False,
                accepted_at=None,
                scope="non-production-internal-test",
                policy_version="1.0.0",
            )
        )


def test_manifest_rejects_a_file_missing_from_lineage() -> None:
    extra_file = quarantined_file(artifact=raw_artifact(artifact_id="ART-20260805-000099"))
    with pytest.raises(ValidationError, match="no missing and no extra"):
        manifest(files=(quarantined_file(), extra_file), total_size_bytes=2468)


def test_manifest_rejects_lineage_with_an_extra_artifact_not_in_files() -> None:
    stray = raw_artifact(artifact_id="ART-20260805-000099")
    file = quarantined_file()
    envelope = ArtifactEnvelope(
        artifact_id=MANIFEST_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.UPLOAD_MANIFEST,
        schema_version="1.0.0",
        content_ref="manifest/upload-manifest.payload.json",
        content_hash=HASH_B,
        producer=ArtifactProducer(component="c", version="0.1.0"),
        input_artifacts=(file.artifact, stray),
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="no missing and no extra"):
        manifest(artifact=envelope)


def test_manifest_rejects_same_artifact_id_with_different_hash_across_files() -> None:
    file_a = quarantined_file(sha256=HASH_A)
    file_b = quarantined_file(
        artifact=raw_artifact(content_hash=HASH_B),
        sha256=HASH_B,
    )
    with pytest.raises(ValidationError, match="duplicate artifact IDs"):
        manifest(files=(file_a, file_b), total_size_bytes=file_a.size_bytes + file_b.size_bytes)


def test_manifest_requires_total_size_to_match_the_sum_of_files() -> None:
    with pytest.raises(ValidationError, match="total_size_bytes must equal"):
        manifest(total_size_bytes=999999)


def test_manifest_manual_deletion_required_forbids_expires_at() -> None:
    with pytest.raises(ValidationError, match="cannot carry an automatic expires_at"):
        manifest(expires_at=NOW)


def test_manifest_active_deletion_status_forbids_deletion_timestamps() -> None:
    with pytest.raises(ValidationError, match="cannot carry deletion timestamps"):
        manifest(deletion_requested_at=NOW)


def test_manifest_rejects_absolute_manifest_content_ref() -> None:
    file = quarantined_file()
    envelope = ArtifactEnvelope(
        artifact_id=MANIFEST_ARTIFACT_ID,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.UPLOAD_MANIFEST,
        schema_version="1.0.0",
        content_ref="/absolute/manifest.json",
        content_hash=HASH_B,
        producer=ArtifactProducer(component="c", version="0.1.0"),
        input_artifacts=(file.artifact,),
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="relative to the package"):
        manifest(artifact=envelope)
