# Architecture Documentation — Overview

BidFusion has two deliberate architecture views:

| View | Audience | Document |
| ---- | -------- | -------- |
| **Concept architecture** | Everyone: engineers, architects, bid managers, pre-sales, sales, management, new team members | [concept-architecture.md](./concept-architecture.md) (also in the root [README](../../README.md)) |
| **Engineering architecture** | Engineers and architects | [engineering-architecture.md](./engineering-architecture.md) |

## Reading guide

1. [Concept architecture](./concept-architecture.md) — what BidFusion
   does, in one diagram and a few paragraphs.
2. [Engineering architecture](./engineering-architecture.md) — the
   domains (A–L), cross-cutting layers, and how they map to the codebase.
3. [Data flow](./data-flow.md) — the pipeline stages and the versioned
   intermediate artifacts between them.
4. [Processing and business state](./state-machine.md) — separate
   technical-run progress, bid lifecycle, and security decisions.
5. [Trust boundaries](./trust-boundaries.md) — where untrusted data ends,
   what the security gate protects, and how data isolation works.
6. [Provenance](./provenance.md) — the contract chain for important
   source-derived claims and the runtime work still required.

## Decisions

Architectural decisions are recorded as ADRs in
[../adr/](../adr/README.md). Read those for the *why*; read the documents
here for the *what* and *how*.
