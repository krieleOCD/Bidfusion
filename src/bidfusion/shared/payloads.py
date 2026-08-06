"""Canonical artifact-payload serialization and sealing (hash convention v1).

Convention ``bidfusion-artifact-payload:1``:

- The canonical payload document is the deterministic JSON serialization of
  ``{hash_convention, artifact_type, schema_version, domain, payload}``.
  ``payload`` contains **all** non-envelope fields of the artifact model and
  is derived automatically from the validated model via
  ``model_dump(mode="json", exclude={"artifact"})`` — never from a manually
  maintained field list, so a new model field can never silently stay
  unhashed.
- ``artifact_type``, ``schema_version``, and ``domain`` are part of the
  hashed projection, so empty payloads of different artifact kinds never
  share a semantic hash space.
- ``ArtifactEnvelope.content_ref`` points at the persisted canonical payload
  file, and ``content_hash`` is the SHA-256 of exactly those bytes. This is
  the Foundation meaning of the envelope hash, and it makes the payload file
  **the sole authoritative source for every artifact content field** — no
  other file may originate or override one.
- The envelope itself (``artifact_id``, ``producer``, ``input_artifacts``,
  ``created_at``, ``content_hash``, ...) is *not* part of the payload file —
  it is excluded by construction, because it is what the payload hash binds
  to (an envelope embedded in its own hash input would be circular).
  Reconstructing and verifying a *complete* sealed artifact therefore
  requires the envelope from a separate source in addition to the payload
  file.
- A full envelope-plus-payload audit file (``….audit.json``) may be
  persisted additionally as a derived, human-inspectable convenience view.
  Its own duplicate copy of the content fields is never authoritative and
  must never be used to reconstruct a model or to decide what is displayed
  or trusted — only the payload file may supply content. Today the audit
  file is still the practical source for the envelope shell a reader needs
  to reconstruct a complete model instance (per the point above, the
  payload file alone is not enough); any reader that consumes it for that
  purpose must independently verify the assembled result with
  :func:`verify_sealed_artifact` before trusting or displaying anything —
  see ``bidfusion.bidrun.quarantine._read_sealed_authoritative`` for the
  reference implementation of this split. The audit file's *claimed*
  envelope is data to be checked, never a trusted input on its own.
- **Security scope.** This sealing scheme, together with the whole-file
  ``integrity-manifest.json`` digest, is tamper-*evident*: it reliably
  detects accidental corruption or a careless, internally inconsistent
  edit. It is not tamper-*proof* and has no external trust anchor — it is
  entirely self-contained and unkeyed. An actor able to rewrite a payload
  file, its envelope, its content hash, and the integrity manifest all
  consistently with each other produces something this scheme cannot
  distinguish from a genuine, untampered artifact. Strong authenticity
  against that threat is out of scope for this convention and would
  require a later, separate mechanism — for example a signature, a keyed
  MAC, an append-only store, or a digest anchored in an external system of
  record.

Sealing a self-referential artifact (a model that embeds its own envelope)
is a two-pass construction: the model is first built against a placeholder
envelope, its automatically derived payload is hashed, and the model is
rebuilt against the final envelope carrying that hash.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from typing import Any, Protocol

from bidfusion.schemas.artifact import (
    ArtifactEnvelope,
    ArtifactProducer,
    ArtifactReference,
    ArtifactType,
)
from bidfusion.schemas.ids import ArtifactId, BidId, RunId

HASH_CONVENTION = "bidfusion-artifact-payload:1"

_PLACEHOLDER_HASH = "0" * 64


class EnvelopedArtifact(Protocol):
    """Structural contract of every model that embeds its own envelope."""

    @property
    def artifact(self) -> ArtifactEnvelope: ...

    def model_dump(self, *, mode: str, exclude: set[str]) -> dict[str, Any]: ...


def canonical_payload_document(
    *,
    artifact_type: ArtifactType,
    schema_version: str,
    domain: str,
    payload: object,
) -> bytes:
    """Serialize one domain-separated canonical payload document."""
    document = {
        "hash_convention": HASH_CONVENTION,
        "artifact_type": artifact_type.value,
        "schema_version": schema_version,
        "domain": domain,
        "payload": payload,
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def artifact_payload_bytes(model: EnvelopedArtifact, *, domain: str) -> bytes:
    """Canonical payload bytes of a sealed artifact model.

    The payload is derived automatically from the model; the embedded
    envelope is the only excluded field.
    """
    envelope = model.artifact
    return canonical_payload_document(
        artifact_type=envelope.artifact_type,
        schema_version=envelope.schema_version,
        domain=domain,
        payload=model.model_dump(mode="json", exclude={"artifact"}),
    )


def payload_digest(payload_bytes: bytes) -> str:
    """SHA-256 digest of canonical payload bytes."""
    return sha256(payload_bytes).hexdigest()


def verify_sealed_artifact(model: EnvelopedArtifact, *, domain: str) -> None:
    """Fail loudly when a sealed artifact does not match its payload hash.

    Proves internal self-consistency only — that ``model``'s content
    hashes to what its own envelope claims. It has no external trust
    anchor and cannot detect a consistently rewritten payload, envelope,
    and hash (see the module docstring's "Security scope" note).
    """
    observed = payload_digest(artifact_payload_bytes(model, domain=domain))
    if observed != model.artifact.content_hash:
        msg = (
            f"artifact {model.artifact.artifact_id} content hash does not match "
            "its canonical payload"
        )
        raise ValueError(msg)


def seal_artifact[ModelT: EnvelopedArtifact](
    build: Callable[[ArtifactEnvelope], ModelT],
    *,
    artifact_id: ArtifactId,
    bid_id: BidId,
    run_id: RunId,
    artifact_type: ArtifactType,
    schema_version: str,
    domain: str,
    content_ref: str,
    producer_component: str,
    producer_version: str,
    input_artifacts: tuple[ArtifactReference, ...],
    created_at: datetime,
) -> ModelT:
    """Two-pass construction binding the envelope hash to the full payload."""

    def envelope_with(content_hash: str) -> ArtifactEnvelope:
        return ArtifactEnvelope(
            artifact_id=artifact_id,
            bid_id=bid_id,
            run_id=run_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            content_ref=content_ref,
            content_hash=content_hash,
            producer=ArtifactProducer(
                component=producer_component,
                version=producer_version,
            ),
            input_artifacts=input_artifacts,
            created_at=created_at,
        )

    draft = build(envelope_with(_PLACEHOLDER_HASH))
    digest = payload_digest(artifact_payload_bytes(draft, domain=domain))
    return build(envelope_with(digest))
