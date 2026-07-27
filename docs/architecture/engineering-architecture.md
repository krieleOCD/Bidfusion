# Engineering Architecture

The **Level 2** view: how BidFusion is structured for engineers. The
concept view lives in [concept-architecture.md](./concept-architecture.md);
decisions are recorded in [../adr/](../adr/README.md).

BidFusion starts as a **modular monolith**: cleanly separated domain
packages in one repository and one deployable. Splitting into services is
a later decision that needs a real reason — no speculative microservices,
event buses, or distributed runtimes.

## Domains

Each domain maps to a package under `src/bidfusion/`.

### Domain A — RFP Intake (`intake/`)

Target responsibility: receive a bid package, create a `Bid` related to an
upstream `Opportunity`, register files, detect upload completion, and start
a `ProcessingRun`. No intake runtime exists yet. A **bid is the top-level
bid-data isolation unit**: every pipeline artifact carries one `bid_id`.

### Domain B — Security Gate (`security/`)

> Security before intelligence.

The contract boundary requires `SecurityClearedArtifact` rather than a raw
path or storage reference. It binds the exact artifact/hash to scanner and
policy versions and the decision audit. `MANUAL_REVIEW` remains pending
until an actor records release or rejection. `BLOCK`, `QUARANTINE`, pending,
and rejected results cannot construct the handoff. Checks include
(long-term): file extension,
MIME type, magic bytes, file signature, size, allowed types, manipulated
or corrupted files, archives, executables, macros, embedded objects,
malware, dangerous payloads, prompt injection and hidden instructions.

Verdicts: `ALLOW` / `MANUAL_REVIEW` / `QUARANTINE` / `BLOCK`. On `BLOCK`
or `QUARANTINE` the normal pipeline stops for that document. Parser API
enforcement, authorization and scanner isolation remain runtime and
operational work; see [trust-boundaries.md](./trust-boundaries.md).

### Domain C — Document Inventory (`inventory/`)

> What did we actually receive?

An RFP is not one document but a **package of related documents**. The
inventory records at minimum: `bid_id`, `document_id`, `filename`,
`file_type`, `mime_type`, `hash`, `size`, `page_count`, `language`,
`security_status`, `classification`, `processing_status`,
`parent_document`, `version` (see `DocumentInventoryEntry` in
`src/bidfusion/schemas/document.py`). Contract validation rejects
downstream in-progress/completed processing for `BLOCK`, `QUARANTINE`, or
pending `MANUAL_REVIEW`, and rejects downstream review for terminal block
or quarantine outcomes.

### Domain D — Document Understanding (`document_understanding/`)

Technical understanding of documents, **strictly separated** from business
extraction. Modules: PDF/DOCX/spreadsheet/CSV/PowerPoint parsers, OCR,
layout analysis, table understanding, figure/diagram understanding,
vision processing, language detection.

> Parse once, use everywhere.

Output is the **canonical document model** (ADR-0003): `Document →
Metadata, Pages → Sections / Paragraphs / Tables → Rows → Cells / Figures
/ Footnotes, Relationships, Source References`. Business agents work on
this model, not on raw files. Contract: `CanonicalDocument` in
`src/bidfusion/schemas/document.py`.

### Domain E — Business Extraction (`extraction/`)

Fan-out/fan-in of **atomic agents** (ADR-0004), each with one clearly
bounded business responsibility — no universal mega-prompts. Examples:
requirement, formalities, deadline, milestone, scope, commercial,
security, compliance, contract, entity and submission extractors, plus
cross-reference and document-relationship resolvers. Agent structure:
[../agents/agent-standard.md](../agents/agent-standard.md).

Every requirement gets a stable ID (e.g. `REQ-000123`) and separates
obligation modality (`MUST` / `SHOULD` / `MAY` / …) from business category
(`SECURITY` / `COMMERCIAL` / `TECHNICAL` / …). It carries confidence,
dependencies, cross references, a canonical **source reference**, and
extraction metadata. Contract:
`Requirement` in `src/bidfusion/schemas/extraction.py`.

Foundation 1.2 applies the same minimal source-bound observation pattern to
formality, scope, commercial, bid-content security, and compliance
payloads. Each of the eight streams has one focused result contract over
shared job metadata and artifact lineage (ADR-0012). The Foundation 1.1
three-payload `ExtractionResult` remains compatibility-only and does not
grow.

### Domain F — Provenance (`provenance/`)

> Important source-derived claims must carry traceable evidence.

Canonical blocks, extracted facts, normalized references, important Working
Package statements, artifact transformations, and positive knowledge claims
have explicit provenance contracts (ADR-0006). Runtime dereferencing and UI
navigation remain future work. See [provenance.md](./provenance.md).

### Domain G — Normalization / Fan-In (`normalization/`)

Extraction results are not copy-pasted together. The
`NormalizedBidDataset` contract is the explicit fan-in boundary with typed
references for requirements, deadlines, entities, formalities, scope,
commercial/security/compliance findings, relationships, conflicts,
provenance, artifact lineage, and explicit expected/completed/failed/skipped
extraction streams. The derived completeness state is `COMPLETE`, `PARTIAL`,
or `FAILED`. Normalization logic is not implemented.

### Domain H — Quality Assurance (`quality/`)

Quality gate after extraction and normalization: missing pages, parsing
errors, OCR quality, extraction and requirement coverage, missing sources,
contradictions, low confidence, missing mandatory criteria, cross
reference errors, deadline conflicts.

> Prefer `UNKNOWN` / `UNCLEAR` / `REQUIRES_REVIEW` over invented
> information.

### Domain I — AI Validation and Business Review

Human-in-the-loop is a fundamental design principle, especially for
critical information: submission deadline, knock-out criteria, MUST
requirements, contractual, security, pricing and compliance requirements.
AI/extraction validation and corrections use `HumanReview` in
`src/bidfusion/schemas/quality.py`. Cross-functional governance uses
separate `BusinessReview`, `ReviewFinding`, and `Approval` contracts.
No Pink/Red/Gold workflow logic is implemented.

### Domain J — Bid Working Package (`working_package/`)

The first **human-oriented product**, valuable before any matching exists.
Audiences: bid managers, sales, pre-sales, solution architects, security,
legal, commercial, management. Contents: executive overview, timeline,
submission instructions, requirements overview, critical requirements,
risks and open questions. Important claims use `EvidencedStatement`, so
their sources and normalized-object links are local to each claim rather
than stored in one global evidence list. Contract:
`WorkingPackage` in `src/bidfusion/schemas/working_package.py`.

### APMP-aligned Bid Management Boundary

APMP is a vendor-neutral domain reference, not a software dependency and
not a claim that BidFusion implements APMP. Foundation 1.1 reserves only
the boundaries that prevent redesign during migration: `Opportunity`,
`BidDecision`, `Actor`, `Assignment`, `ComplianceMatrix`,
`BusinessReview`, `Approval`, and governed knowledge. Strategy, scoring,
full review workflows, submission, post-bid, and lessons learned remain
later domains. See [ADR-0010](../adr/0010-apmp-aligned-bid-management-domain.md).

### Bid Intelligence (`bid_intelligence/`) — separate domain, prepared only

After the working package, pure RFP analysis ends. Everything beyond —
capability matching, coverage analysis, gap analysis, SME routing,
clarification questions, bid strategy, response generation — is a
separate domain with its own pipeline, **architecturally prepared but not
implemented**.

### Domain K — Governed Knowledge (`golden_dataset/`)

> Knowledge base, not RFP input.

`KnowledgeItem` and `KnowledgeGovernance` reserve owner, approval status,
version, validity, review cycle, classification, source, and evidence for
enterprise knowledge. Bid data and governed knowledge remain separated;
normal bid matching is read-only against knowledge (ADR-0009). No
retrieval system or knowledge store is implemented.

### Domain L — Capability Matching (`bid_intelligence/matching/`)

Matching is **not** "find a semantically similar paragraph". Embeddings
may support candidate retrieval (alongside BM25 and metadata filters);
they are not the matching engine. The target flow: candidate retrieval →
candidate capabilities → evidence validation → reasoning/classification →
`SUPPORTED` / `PARTIALLY_SUPPORTED` / `NOT_SUPPORTED` / `UNKNOWN`.

> No evidence → no positive capability claim.

This invariant is enforced by `CapabilityMatch`: positive claims require
approved evidence snapshots valid at evaluation time and tied to the
matched capability (`src/bidfusion/schemas/intelligence.py`). A later
runtime must verify the snapshot against the authoritative knowledge store.
Matching produces separate
products — coverage matrix, gap analysis, SME/presales tasks, response
evidence — not a bid draft.

## Cross-cutting layers

### External Capability Ports — ADR-0011

> BidFusion owns contracts. Providers are adapters.

`src/bidfusion/ports.py` defines only three minimal structural boundaries:
`LLMPort.generate`, `OCRPort.extract`, and `ArtifactStore.put/get`. Their
arguments and results are strict BidFusion models. Provider SDK objects,
backend objects, credential values, and direct provider selection cannot
cross these boundaries.

`ExternalCapabilityError` retains no provider message or SDK payload and
exposes one normalized code: unavailable, timeout, rate limited,
authentication failed, invalid response, or policy blocked.
`ProviderConfig` carries a required endpoint, an optional `SecretRef`, and
a bounded non-sensitive timeout. It has no API-key, token, password, or
secret-value field.

Foundation 1.2 includes contract-only, deterministic test fakes. It does
not include a provider adapter, OCR engine, storage backend, plugin system,
secret manager, retry policy, or any real external integration.

### LLM Gateway (`llm_gateway/`) — ADR-0007

Model-agnostic integration through `LLMPort`. Agents construct
`LLMRequest` and declare requirements, never providers:

```yaml
capabilities:
  vision: true
  structured_output: true
  reasoning: medium
  context_window: large
data_policy:
  classification: CONFIDENTIAL
  local_processing_preferred: true
cost_priority: medium
```

Bid-bound input artifacts require an `ExecutionScope` and every input must
match its `bid_id`. Prompt-only non-bid requests may remain unscoped.
This is contract isolation; runtime authorization, access control, prompt
isolation, and cache isolation remain future enforcement.

The future gateway adapter decides model, provider, deployment, fallback
and routing. No provider logic or provider SDK type belongs in business
agents.

### OCR (`document_understanding/ocr/`)

`OCRRequest` accepts the exact `SecurityClearedArtifact` handoff.
`OCRResult` returns owned, ordered text blocks with confidence, page/block
locators, original-document hashes, and artifact lineage. These blocks are
ready for a later canonical mapper; no OCR engine or mapping runtime exists.

### Artifact Storage (`storage/`)

`ArtifactStore` reserves only immutable content `put` and `get` operations
using `ArtifactEnvelope` and `ArtifactReference`. Selection of local,
database, or object storage and enforcement of write-once/hash/access
semantics remain later work.

### Observability (`observability/`)

`ProcessingRun`, artifact envelopes, and extraction metadata reserve IDs,
versions, status, timestamps, model route, errors, and review links. The
observability runtime and its content-redaction policy are not implemented.

### Evaluations (`evals/`)

LLM components get evals, not just unit tests: requirement
recall/precision, classification, deadline, metadata, citation, table and
cross-reference accuracy, hallucination rate, capability matching
accuracy. Dummy RFPs from `fixtures/synthetic/` form the benchmark
dataset. See [../development/evals.md](../development/evals.md).

### Security & Data Isolation

Contracts reject modeled cross-bid combinations at central boundaries.
Tenant isolation, access control, encryption, secrets management, retention,
deletion, audit logging, prompt/cache isolation, and content-safe logging
remain runtime/operational requirements. Customer documents are prohibited
from git by repository policy. See
[trust-boundaries.md](./trust-boundaries.md) and
[../../SECURITY.md](../../SECURITY.md).

### Orchestration (`orchestration/`)

Target responsibility: coordinate technical stages, dependencies, retries,
failure handling, waiting, and resume — **no business logic**. Foundation
1.1 defines `ProcessingRun`; it does not implement orchestration or
idempotency. See [state-machine.md](./state-machine.md).
