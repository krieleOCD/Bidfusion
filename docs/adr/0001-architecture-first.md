# ADR-0001: Architecture First, Migration Second

**Status:** ACCEPTED

## Context

Various local modules, agents, security components, LLM integrations and
experiments already exist outside this repository. Letting them shape the
new system would freeze accidental structures into place. The existing
components reflect what was built ad hoc — not what the system should be.

## Decision

We design the ideal target architecture first, in this repository, without
looking at existing implementations. Only after a human review has
accepted the target architecture do we inventory the existing components,
map them to target modules (`Keep / Move / Refactor / Split / Merge /
Replace / Deprecate`, see
[../development/component-migration.md](../development/component-migration.md))
and migrate what is worth migrating.

Order of work:

```text
TARGET ARCHITECTURE → HUMAN REVIEW → EXISTING COMPONENT INVENTORY
→ MIGRATION MAPPING → IMPLEMENTATION
```

## Consequences

- The repository starts clean, without legacy compromises.
- Existing components may turn out to be partially redundant or
  misaligned; that is an acceptable cost.
- Migration is delayed until the target is agreed — slower to first code,
  faster to a coherent system.
- This ADR governs the current phase and is already in effect; the
  target-architecture ADRs (0002–0009) become binding with the human
  foundation review.
