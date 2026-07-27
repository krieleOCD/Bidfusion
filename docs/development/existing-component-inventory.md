# Existing Component Inventory

Phase 2 inventory against the frozen `foundation-1.2` baseline. Inventory
records what the source actually does. It does not authorize copying or
migration.

The mandatory decision flow is:

```text
Existing Component
→ Target Module
→ Migration Decision
→ Required Changes
→ Required Tests
```

Allowed decisions are `KEEP`, `MOVE`, `REFACTOR`, `SPLIT`, `MERGE`,
`REPLACE`, and `DEPRECATE`.

## Candidate 001 — Security Gate

Source inspected read-only: local `bidfusion-security-gate/` component
directory outside the product repository.

Observed state:

- executable FastAPI and CLI prototype, but not a Git repository;
- deterministic preflight checks for size, detected MIME type, macros,
  PDF JavaScript, embedded objects, encryption, metadata, and SHA-256;
- direct Mistral OCR, moderation, worker, and synthesizer calls;
- security, legal, ethics, PII, bid analysis, orchestration, and UI
  concerns combined in one application;
- worker exceptions represented as `passed=True`, which is incompatible
  with the Foundation fail-closed decision;
- mutable local Pydantic result models with `PASS` / `REVIEW` / `BLOCK`,
  rather than the accepted hash-bound Foundation contracts; and
- no automated test files in the source `tests/` directory. Evaluation
  outputs and customer-like documents are evidence for review only, not
  migration tests or product fixtures.

Overall decision: `SPLIT`. The first migration slice is the deterministic
preflight row below. No source file, local `.env`, customer document,
evaluation output, generated report, or demo asset may be copied into the
product repository as part of inventory.

| Existing Component | Target Module | Migration Decision | Required Changes | Required Tests |
| ------------------ | ------------- | ------------------ | ---------------- | -------------- |
| `security/preflight.py` deterministic file checks and SHA-256 calculation | `src/bidfusion/security/` | `REFACTOR` | Retain useful pure checks, but accept BidFusion-owned artifact identity instead of an unbound path; produce `SecurityResult` with exact `bid_id`, `document_id`, artifact/hash, scanner version, policy version, decision time, and Foundation verdicts; treat unknown types, corrupt inputs, and scanner failures as non-allowing outcomes; keep clearance construction separate. | Unit tests for size/type allowlists, extension versus magic-byte mismatch, corrupt files, macros, PDF JavaScript, embedded objects, encryption, and deterministic hashes; adversarial tests proving errors never yield `ALLOW`; contract tests for exact bid/document/artifact/hash binding and prevention of clearance after `BLOCK`, `QUARANTINE`, or pending/rejected review. |
| `agent/tools/injection_worker.py`, `agent/tools/techsec_worker.py`, and Mistral moderation used as security analysis | `src/bidfusion/security/` through `LLMPort` | `REFACTOR` | Isolate security-scanner prompts from downstream business intelligence; replace direct SDK calls and provider model names with owned requests and normalized failures; bind findings to the exact artifact and policy; on timeout, parse error, or worker failure return a non-allowing result. | Fake-port tests for normalized success and every failure class; prompt-injection and encoded-payload regressions; tests proving partial worker failure cannot produce clearance; evidence and hash-binding tests. |
| `security/preflight.py::extract_text_with_mistral` and local extraction fallbacks | `src/bidfusion/document_understanding/ocr/` plus an `OCRPort` adapter | `SPLIT` | Remove OCR from the deterministic preflight unit; perform any scanner-required extraction inside the isolated gate, while normal downstream OCR accepts only `SecurityClearedArtifact`; move provider translation behind an adapter without selecting a new provider architecture. | Port conformance and normalized-failure tests; tests proving normal OCR rejects uncleared input; extraction fallback and content-hash continuity tests. |
| `agent/tools/pii_worker.py`, `legal_worker.py`, `ethics_worker.py`, and `rfp_analyzer.py` | `src/bidfusion/extraction/`, `src/bidfusion/quality/`, and `src/bidfusion/bid_intelligence/` according to responsibility | `SPLIT` | Do not carry business analysis through the Security Gate. Inventory each worker separately before migration, make it atomic, consume canonical documents rather than raw text, and emit the focused typed extraction or intelligence contract with provenance. | Per-agent contract, provenance, bid-isolation, empty-result, failure, and evaluation tests; tests proving no worker accepts raw or merely scanned content. |
| `agent/orchestrator.py` and `workflow/` pipelines | `src/bidfusion/orchestration/` | `REPLACE` | Replace provider-bound mega-workflows with stage coordination over owned ports and artifacts; remove business verdict logic from orchestration; enforce fail-closed gate transitions and do not adopt a workflow framework through migration. | State-transition tests for allow, manual review, quarantine, block, timeout, retry, and partial failure; tests proving no downstream stage runs before an exact clearance. |
| `models/schemas.py` security and analysis models | Existing contracts in `src/bidfusion/schemas/` | `REPLACE` | Use the frozen Foundation schemas. Map `PASS` to `ALLOW`, map `REVIEW` only to pending `MANUAL_REVIEW`, and map `BLOCK` to a non-allowing policy outcome; never infer an audited manual release. Do not migrate mutable duplicate contracts. | Schema-validation and serialization tests; explicit verdict-mapping tests; tests proving `REVIEW` alone cannot construct `SecurityClearedArtifact`. |
| `app.py`, `main.py`, `static/`, demo scripts, generated reports, and evaluation outputs | None in the first migration slice | `DEPRECATE` | Keep outside the product repository as reference material. Reconsider a product-facing adapter only after the gate contract and runtime module pass their required tests. | No migration tests; later UI/API work requires separate acceptance and boundary tests. |

## Next controlled action

Prepare the first implementation plan only for the deterministic preflight
row. Its source functions must be reviewed individually before any code is
moved. The Foundation remains unchanged.
