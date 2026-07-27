# Architecture Decision Records

ADRs record the significant architectural decisions of BidFusion: the
*why* behind the architecture. They are short on purpose — one decision
per record.

## Format

```text
Status       PROPOSED | ACCEPTED | SUPERSEDED by ADR-XXXX
Context      What forces a decision?
Decision     What was decided?
Consequences What follows from it (positive and negative)?
```

## Status conventions

- **ACCEPTED** — explicitly approved and in effect.
- **PROPOSED** — decided on paper as part of the target architecture,
  pending explicit human confirmation.
- **SUPERSEDED** — replaced by a later ADR, which is named in the status.

## Index

| ADR | Title | Status |
| --- | ----- | ------ |
| [0001](./0001-architecture-first.md) | Architecture First, Migration Second | ACCEPTED |
| [0002](./0002-security-before-intelligence.md) | Security Before Intelligence | ACCEPTED |
| [0003](./0003-canonical-document-model.md) | Canonical Document Model | ACCEPTED |
| [0004](./0004-atomic-agents.md) | Atomic Agents over Monolithic Agent | ACCEPTED |
| [0005](./0005-schema-first.md) | Schema-First Integration | ACCEPTED |
| [0006](./0006-provenance-first.md) | Provenance as First-Class Concept | ACCEPTED |
| [0007](./0007-model-agnostic-llm-gateway.md) | Model-Agnostic LLM Integration | ACCEPTED |
| [0008](./0008-intermediate-artifacts.md) | Intermediate Pipeline Artifacts | ACCEPTED |
| [0009](./0009-separate-bid-data-and-golden-data.md) | Bid Data and Governed Knowledge Separation | ACCEPTED |
| [0010](./0010-apmp-aligned-bid-management-domain.md) | APMP-aligned Bid Management Domain | ACCEPTED |
| [0011](./0011-external-capabilities-via-ports-and-adapters.md) | External Capabilities via Ports and Adapters | ACCEPTED |
| [0012](./0012-focused-typed-extraction-results.md) | Focused Typed Extraction Results | ACCEPTED |

## Rules

- Every significant architectural decision gets an ADR — before or with
  the change, not after.
- ADRs are immutable once accepted; changing a decision means a new ADR
  that supersedes the old one.
- Naming: `NNNN-short-kebab-title.md`, numbers monotonically increasing.
