# ADR-0005: Schema-First Integration

**Status:** ACCEPTED

## Context

Many modules exchange data: intake, security, inventory, parsers,
extraction agents, normalization, QA, working package, matching. Without
defined contracts, integration degenerates into "Agent A produces some
JSON, Agent B hopes it fits" — failures surface late and far from their
cause.

## Decision

All interfaces between modules are **defined schemas**: Pydantic models as
the single source of truth (`src/bidfusion/schemas/`), with JSON Schemas
derived from them for non-Python consumers
(`scripts/export_schemas.py`). Contracts are strict — undeclared fields
are rejected — and versioned through normal code review. Typed Python
interfaces complement the models inside the codebase.

## Consequences

- Integration errors are caught at validation time, at the boundary where
  they occur.
- Contracts are part of the architecture: changing one is an explicit,
  reviewable decision.
- Some upfront modeling effort; schema evolution requires discipline
  (additive changes preferred, breaking changes coordinated).
- Architectural invariants can be enforced *by the contracts* — e.g.
  `CapabilityMatch` rejects positive capability claims without evidence.
