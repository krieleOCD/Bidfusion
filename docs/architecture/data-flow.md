# Data Flow and Artifact Lineage

Foundation 1.2 defines typed transformation boundaries. The first Phase 2
slice implements deterministic preflight assessment, but not complete gate
policy, pipeline orchestration, or an artifact storage backend.

## Target flow

```text
Raw Artifact
    ↓ PreflightAssessment bound to exact hash
Security assessments
    ↓ Gate policy
SecurityResult bound to exact hash
    ↓ ALLOW or audited manual release
SecurityClearedArtifact
    ↓
Document Inventory
    ↓
Canonical Document Artifact
    ↓
Atomic Extraction Result Artifacts
    ↓
NormalizedBidDataset Artifact
    ↓
QA / AI Validation / Business Review
    ↓
Bid Working Package Artifact
    ↓
Compliance Matrix / later Bid Intelligence
```

`MANUAL_REVIEW` pauses at the security boundary. An audited release may
create the same typed handoff as `ALLOW`; rejection, `BLOCK`, and
`QUARANTINE` cannot.

`PreflightAssessment` contains observations only. Even when every
deterministic check reports `PASS` or `NOT_APPLICABLE`, it cannot construct
`SecurityClearedArtifact` and does not imply `ALLOW`. Gate policy combines
all required assessments into the final `SecurityResult`.

## Artifact contract

Every persisted pipeline product is represented by `ArtifactEnvelope`:

```yaml
artifact_id: ART-20260727-000004
bid_id: BID-2026-000123
run_id: RUN-20260727-0001
artifact_type: normalized_bid_dataset
schema_version: 1.0.0
producer:
  component: normalization
  version: 1.1.0
input_artifacts:
  - artifact_id: ART-20260727-000003
    bid_id: BID-2026-000123
    run_id: RUN-20260727-0001
    artifact_type: extraction_result
    schema_version: 1.0.0
    content_ref: artifacts/ART-20260727-000003
    content_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
created_at: 2026-07-27T10:00:00Z
content_ref: artifacts/ART-20260727-000004
content_hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
```

The envelope supports schema evolution, producer versioning, input lineage,
reproducibility, audit, and resume decisions. `ArtifactReference` is the
immutable reference form used between contracts.

## Explicit fan-in

`NormalizedBidDataset` is the first-class fan-in boundary. It has typed
collections for requirement, deadline, entity, formality, scope,
commercial, security, and compliance-finding references, plus
relationships and unresolved conflicts. Every normalized reference retains
its extraction artifacts and source references. It is intentionally not an
unstructured mega-dictionary.

Each upstream extraction stream has a focused result, such as
`RequirementExtractionResult`, `FormalityExtractionResult`, or
`ComplianceExtractionResult`. The Foundation 1.1 `ExtractionResult`
remains only as a compatibility envelope for its original three payloads;
new streams do not add fields to it.

The dataset also carries `ExtractionCompleteness`: expected, completed,
failed, and skipped streams with a derived `COMPLETE`, `PARTIAL`, or
`FAILED` state. An empty result from a completed extractor is therefore
different from an extractor that did not successfully run.

## Contract-enforced now

- strict envelope fields and semantic schema/producer versions;
- frozen validated contracts and a central `ArtifactType` enum;
- exact SHA-256 references;
- no self-reference, duplicate input IDs, or modeled cross-bid lineage;
- normalized object-type consistency, source-artifact lineage, and
  extraction completeness; and
- source-dataset lineage on compliance matrices and working packages.

## Runtime-enforced later

- content hash verification on reads and writes;
- write-once artifact persistence and retention;
- deterministic/idempotent step behavior;
- resume selection from completed artifacts; and
- schema migration and compatibility policy.

## Candidate local layout

The storage package may later implement a layout such as:

```text
data/artifacts/
└── BID-2026-000123/
    └── RUN-20260727-0001/
        ├── security/
        ├── inventory/
        ├── canonical/
        ├── extraction/
        ├── normalized/
        ├── working-package/
        └── compliance/
```

This is a convention, not an implemented guarantee or storage decision.

## MVP artifact persistence and hash semantics

The local walking-skeleton pipeline seals self-referential artifacts
(canonical documents, extraction results, the normalized dataset, the
working package, and — for the upload-quarantine slice — the
`UploadManifest` and `BidRunRecord`) under the versioned convention
`bidfusion-artifact-payload:1` (`src/bidfusion/shared/payloads.py`):

- The **canonical payload file** at `ArtifactEnvelope.content_ref`
  (`….payload.json`) is **the sole authoritative source for every artifact
  content field**. `content_hash` is the SHA-256 of exactly those bytes —
  the Foundation meaning of the envelope hash.
- The hashed projection contains `hash_convention`, `artifact_type`,
  `schema_version`, and a `domain` discriminator (for example
  `extraction/requirement`), so empty payloads of different artifact kinds
  never share a hash space. The payload itself is derived automatically
  from the validated model (every non-envelope field); there is no manually
  maintained field list that a new model field could silently miss.
- The **artifact envelope** (`artifact_id`, `producer`, `input_artifacts`,
  `created_at`, `content_hash`, …) is stored separately from the payload —
  it is excluded from the hashed payload by construction, since it is what
  the payload hash binds to. Reconstructing and verifying a *complete*
  sealed artifact therefore needs the envelope from a separate source in
  addition to the payload file.
- A full envelope-plus-payload `….audit.json` file is written as a derived
  convenience view. Its own duplicate copy of the content fields is
  **never authoritative and must never be used to reconstruct a model or
  to decide what is displayed or trusted** — content only ever comes from
  the payload file. Today the audit file is still the practical source of
  the envelope shell needed to reconstruct a complete model instance (the
  payload file alone excludes it, per the point above); a reader that
  consumes the audit file for that purpose must independently re-verify
  the assembled result with `verify_sealed_artifact()` before trusting or
  displaying anything — see `bidfusion.bidrun.quarantine.read_quarantine_package`
  for the reference read path. On any deviation, the payload file governs
  and the read is rejected, never silently resolved in the audit file's
  favor.
- `integrity-manifest.json` in the run (or quarantine package) directory
  records whole-file SHA-256 digests of every file written (payload files,
  audit files, security results, inventory, Markdown, run summary).
  `verify_run_integrity()` re-checks them and reports missing, modified,
  and unlisted files.
- **Security scope.** Package-level SHA-256 sealing — the payload hash plus
  the whole-file integrity manifest — is tamper-*evident*, not
  tamper-*proof*: it has no external trust anchor and is entirely
  self-contained and unkeyed. An actor able to rewrite every payload file,
  its envelope, its content hash, and the integrity manifest consistently
  with each other cannot be detected by this scheme. Strong authenticity
  against such an actor is out of scope here and would need a later,
  separate mechanism — a signature, a keyed MAC, an append-only store, or a
  digest anchored in an external system of record.
