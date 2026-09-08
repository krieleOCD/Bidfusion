"""Tests for the versioned, domain-separated artifact hash convention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol

from bidfusion.document_understanding.canonical import CANONICAL_DOMAIN
from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.extraction.support import extraction_domain
from bidfusion.normalization import merge_extractions
from bidfusion.normalization.merge import NORMALIZED_DOMAIN
from bidfusion.ports import ArtifactStore, ExternalCapabilityError
from bidfusion.quality import evaluate_quality
from bidfusion.schemas import (
    ArtifactEnvelope,
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    ExternalErrorCode,
    NormalizedBidDataset,
    ProcessingStatus,
    RequirementExtractionResult,
    RequirementsSummary,
    Risk,
    SubmissionInstructions,
    WorkingPackage,
)
from bidfusion.schemas.extraction import ExtractionStream
from bidfusion.schemas.normalization import (
    NormalizedObjectType,
    NormalizedRelationship,
    UnresolvedConflict,
)
from bidfusion.schemas.working_package import ExecutiveOverview
from bidfusion.shared.payloads import (
    artifact_payload_bytes,
    canonical_payload_document,
    payload_digest,
    verify_sealed_artifact,
)
from bidfusion.working_package import build_working_package
from bidfusion.working_package.builder import WORKING_PACKAGE_DOMAIN

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


class SealedModel(Protocol):
    """Sealed artifact model that also supports unvalidated field mutation."""

    @property
    def artifact(self) -> ArtifactEnvelope: ...

    def model_dump(self, *, mode: str, exclude: set[str]) -> dict[str, Any]: ...

    def model_copy(self, *, update: dict[str, Any]) -> SealedModel: ...


@dataclass(frozen=True)
class BuiltArtifacts:
    canonical: CanonicalDocument
    requirements: RequirementExtractionResult
    dataset: NormalizedBidDataset
    package: WorkingPackage


def build_all(canonicals: tuple[CanonicalDocument, ...]) -> BuiltArtifacts:
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000021",
        created_at=NOW,
    )
    deadlines = extract_deadlines(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000022",
        created_at=NOW,
    )
    formalities = extract_formalities(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000023",
        created_at=NOW,
    )
    dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000024",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    package = build_working_package(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        quality=quality,
        artifact_id="ART-20260804-000025",
        generated_at=NOW,
    )
    return BuiltArtifacts(
        canonical=canonicals[0],
        requirements=requirements,
        dataset=dataset,
        package=package,
    )


def sealed_variants(artifacts: BuiltArtifacts) -> tuple[tuple[str, SealedModel, str], ...]:
    return (
        ("canonical", artifacts.canonical, CANONICAL_DOMAIN),
        ("requirements", artifacts.requirements, extraction_domain("requirement")),
        ("dataset", artifacts.dataset, NORMALIZED_DOMAIN),
        ("package", artifacts.package, WORKING_PACKAGE_DOMAIN),
    )


def assert_every_field_changes_the_hash(
    model: SealedModel,
    *,
    domain: str,
    mutations: dict[str, object],
) -> None:
    """Every non-envelope field must be covered and must change the hash."""
    baseline = artifact_payload_bytes(model, domain=domain)
    dumped_fields = set(model.model_dump(mode="json", exclude={"artifact"}))
    assert set(mutations) == dumped_fields, (
        "mutation coverage out of sync with model fields: "
        f"missing={sorted(dumped_fields - set(mutations))} "
        f"extra={sorted(set(mutations) - dumped_fields)}"
    )
    for field_name, value in mutations.items():
        mutated = model.model_copy(update={field_name: value})
        assert artifact_payload_bytes(mutated, domain=domain) != baseline, field_name


class ReferenceArtifactStore:
    """In-memory store enforcing the exact-bytes contract of ArtifactStore."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[ArtifactReference, bytes]] = {}

    def put(self, envelope: ArtifactEnvelope, content: bytes) -> ArtifactReference:
        if sha256(content).hexdigest() != envelope.content_hash:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE)
        reference = envelope.as_reference()
        self._entries[reference.artifact_id] = (reference, content)
        return reference

    def get(self, reference: ArtifactReference) -> bytes:
        entry = self._entries.get(reference.artifact_id)
        if entry is None or entry[0] != reference:
            raise ExternalCapabilityError(ExternalErrorCode.UNAVAILABLE)
        return entry[1]


def test_projection_separates_domain_type_and_schema_version() -> None:
    base = canonical_payload_document(
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version="1.0.0",
        domain="extraction/requirement",
        payload=[],
    )

    assert base == canonical_payload_document(
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version="1.0.0",
        domain="extraction/requirement",
        payload=[],
    )
    assert base != canonical_payload_document(
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version="1.0.0",
        domain="extraction/deadline",
        payload=[],
    )
    assert base != canonical_payload_document(
        artifact_type=ArtifactType.WORKING_PACKAGE,
        schema_version="1.0.0",
        domain="extraction/requirement",
        payload=[],
    )
    assert base != canonical_payload_document(
        artifact_type=ArtifactType.EXTRACTION_RESULT,
        schema_version="2.0.0",
        domain="extraction/requirement",
        payload=[],
    )


def test_empty_results_of_different_streams_never_share_a_hash() -> None:
    empty_requirements = extract_requirements(
        (), bid_id=BID_ID, run_id=RUN_ID, artifact_id="ART-20260804-000031", created_at=NOW
    )
    empty_deadlines = extract_deadlines(
        (), bid_id=BID_ID, run_id=RUN_ID, artifact_id="ART-20260804-000031", created_at=NOW
    )

    assert empty_requirements.artifact.content_hash != empty_deadlines.artifact.content_hash


def test_sealed_artifacts_bind_their_full_payload(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    artifacts = build_all(rfp_minimal_canonicals)

    for name, model, domain in sealed_variants(artifacts):
        payload = artifact_payload_bytes(model, domain=domain)
        assert payload_digest(payload) == model.artifact.content_hash, name
        verify_sealed_artifact(model, domain=domain)
        tampered = model.model_copy(update={"bid_id": "BID-2026-999999"})
        try:
            verify_sealed_artifact(tampered, domain=domain)
        except ValueError:
            continue
        raise AssertionError(f"tampered {name} artifact passed verification")


def test_every_working_package_field_is_hashed(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    package = build_all(rfp_minimal_canonicals).package
    portal_statement = package.submission_instructions.portal
    assert portal_statement is not None

    assert_every_field_changes_the_hash(
        package,
        domain=WORKING_PACKAGE_DOMAIN,
        mutations={
            "source_dataset": package.source_dataset.model_copy(
                update={"content_ref": "normalized/other.payload.json"}
            ),
            "bid_id": "BID-2026-999999",
            "version": 2,
            "generated_at": NOW + timedelta(hours=1),
            "executive_overview": ExecutiveOverview(scope_summary=(portal_statement,)),
            "timeline": (),
            "submission_instructions": SubmissionInstructions(),
            "requirements_summary": RequirementsSummary(),
            "critical_requirements": (),
            "risks": (Risk(risk_id="R-1", statement=portal_statement, category="test"),),
            "open_questions": (),
        },
    )


def test_every_extraction_result_field_is_hashed(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements = build_all(rfp_minimal_canonicals).requirements

    assert_every_field_changes_the_hash(
        requirements,
        domain=extraction_domain("requirement"),
        mutations={
            "bid_id": "BID-2026-999999",
            "agent_name": "mutated-agent",
            "agent_version": "9.9.9",
            "prompt_version": "p1",
            "model": "gateway-assigned",
            "document_ids": (),
            "status": ProcessingStatus.FAILED,
            "started_at": NOW + timedelta(minutes=1),
            "finished_at": NOW + timedelta(minutes=2),
            "errors": ("synthetic error",),
            "stream": ExtractionStream.DEADLINE,
            "requirements": (),
        },
    )


def test_every_normalized_dataset_field_is_hashed(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    dataset = build_all(rfp_minimal_canonicals).dataset
    first_ref = dataset.requirements[0]

    def retyped(object_type: NormalizedObjectType, object_id: str) -> object:
        return (first_ref.model_copy(update={"object_type": object_type, "object_id": object_id}),)

    assert_every_field_changes_the_hash(
        dataset,
        domain=NORMALIZED_DOMAIN,
        mutations={
            "bid_id": "BID-2026-999999",
            "completeness": dataset.completeness.model_copy(
                update={"failed_streams": (ExtractionStream.FORMALITY,)}
            ),
            "requirements": (),
            "deadlines": (),
            "entities": retyped(NormalizedObjectType.ENTITY, "ENT-001"),
            "formalities": (),
            "scope": retyped(NormalizedObjectType.SCOPE, "SCOPE-001"),
            "commercial_findings": retyped(NormalizedObjectType.COMMERCIAL_FINDING, "COM-001"),
            "security_findings": retyped(NormalizedObjectType.SECURITY_FINDING, "SEC-001"),
            "compliance_findings": retyped(NormalizedObjectType.COMPLIANCE_FINDING, "CMP-001"),
            "relationships": (
                NormalizedRelationship(
                    bid_id=BID_ID,
                    from_object_id=first_ref.object_id,
                    to_object_id="REQ-000003",
                    kind="depends_on",
                    sources=first_ref.sources,
                ),
            ),
            "unresolved_conflicts": (
                UnresolvedConflict(
                    bid_id=BID_ID,
                    conflict_id="CONF-901",
                    object_ids=(first_ref.object_id, "REQ-000003"),
                    description="synthetic conflict for hash coverage",
                    sources=first_ref.sources,
                ),
            ),
        },
    )


def test_payload_bytes_roundtrip_through_the_artifact_store_contract(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    artifacts = build_all(rfp_minimal_canonicals)
    store = ReferenceArtifactStore()
    assert isinstance(store, ArtifactStore)

    for name, model, domain in sealed_variants(artifacts):
        payload = artifact_payload_bytes(model, domain=domain)
        reference = store.put(model.artifact, payload)
        assert store.get(reference) == payload, name

    tampered = artifact_payload_bytes(artifacts.package, domain=WORKING_PACKAGE_DOMAIN) + b"tamper"
    try:
        store.put(artifacts.package.artifact, tampered)
    except ExternalCapabilityError as failure:
        assert failure.code is ExternalErrorCode.INVALID_RESPONSE
    else:
        raise AssertionError("store accepted bytes that do not match the envelope hash")
