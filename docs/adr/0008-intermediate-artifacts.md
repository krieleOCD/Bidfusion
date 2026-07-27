# ADR-0008: Intermediate Pipeline Artifacts

**Status:** ACCEPTED

## Context

The pipeline has expensive and fallible steps (OCR, parsing, LLM
extraction). Without persisted intermediate results, debugging means
re-running everything, audits are impossible, and a failed step forces a
full restart — including re-paying all LLM costs.

## Decision

The target runtime will persist a **versioned intermediate artifact** after
every important pipeline step:

```text
Raw Package → Security Result → Document Inventory → Parsed Documents
→ Canonical Documents → Extraction Results → Normalized Bid Dataset
→ Working Package
```

`ArtifactEnvelope` and `ArtifactReference` contractually carry artifact,
bid and run IDs, artifact type, schema version, producer/version, input
artifacts and hashes, creation time, content reference and content hash.
The envelope rejects self-references, duplicate inputs and cross-bid
lineage.

Persistence, write-once storage, content-address verification, resume
selection and idempotent execution remain runtime responsibilities. No
storage backend is selected in the Foundation.

## Consequences

- Implementing the contracts in storage will make debugging, audit,
  repeatability and regression testing practical.
- The runtime can later re-run single steps and avoid unnecessary expensive
  processing.
- A storage convention and lifecycle (retention, deletion) become
  necessary — owned by the `storage` package.
- Layout convention: [../architecture/data-flow.md](../architecture/data-flow.md).
