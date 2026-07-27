# ADR-0006: Provenance as First-Class Concept

**Status:** ACCEPTED

## Context

Bid decisions depend on trusting what the system says. In an LLM-supported
pipeline, an unsupported claim is worse than no claim — hallucinated or
misattributed requirements can lose bids or create liability. "Trust me"
is not a strategy; humans must be able to verify.

## Decision

> Important source-derived claims must be traceable to evidence.

Provenance is built into the contracts. `SourceReference` binds a bid,
document, document hash, canonical artifact and typed locator. Canonical
source-derived blocks and extracted objects require it. Normalized object
references retain both sources and input artifact references. Important
Working Package claims use `EvidencedStatement` and link normalized object
IDs to their own sources. Artifact envelopes connect every transformation.
Positive capability claims require approved, current governed-knowledge
evidence.

## Consequences

- Contracts contain the IDs and locators required for a human interface to
  navigate from an important statement to original evidence.
- Auditing, QA and regression testing gain a stable anchor.
- Contract presence, bid isolation, hash binding, and artifact lineage are
  tested. Runtime dereferencing, storage integrity, and UX navigation remain
  future enforcement.
- Documented in [../architecture/provenance.md](../architecture/provenance.md).
