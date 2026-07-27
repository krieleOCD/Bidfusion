# ADR-0009: Bid Data and Governed Knowledge Separation

**Status:** ACCEPTED

## Context

BidFusion handles two fundamentally different kinds of data: **bid data**
(customer-owned, confidential, per-bid, often under contractual handling
rules) and the **Golden Dataset** (curated, approved internal knowledge:
services, capabilities, SLAs, certifications, references). Mixing them —
e.g. letting bid content flow into a shared knowledge base or retrieval
index — risks confidentiality breaches and cross-contamination between
bids and customers.

## Decision

Bid data and Golden Data are **logically and physically separated**:

- Governed knowledge is not RFP input. `KnowledgeItem` and
  `KnowledgeGovernance` reserve owner, approval status, version, validity,
  review cycle, classification, source, and evidence.
- Bid data never flows into the Golden Dataset automatically.
- Bid artifacts are isolated per `bid_id`; retrieval and matching read the
  Golden Dataset but write only per-bid results.
- Data classification is part of the contracts, and the LLM gateway
  applies the declared data policy at the model boundary (ADR-0007).

## Consequences

- The contract boundary prevents modeled cross-bid combinations; runtime
  storage and access controls must prevent leakage through shared systems.
- Positive capability matches accept only evidence snapshots marked
  approved and valid at evaluation time. Runtime lookup must later verify
  that snapshot against the authoritative knowledge store.
- Knowledge captured during a bid (e.g. a new standard answer) requires a
  deliberate curation step — slower, but safe.
