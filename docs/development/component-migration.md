# Component Migration

How existing local components get into BidFusion — **after** the target
architecture has been reviewed and accepted by a human (ADR-0001). This
document defines the procedure. The live Phase 2 record is the
[Existing Component Inventory](./existing-component-inventory.md).

## Preconditions

- Target architecture reviewed and accepted (human review).
- ADRs confirmed or adjusted.

## Procedure

```text
Inventory
   ↓
Classify
   ↓
Map
   ↓
Evaluate
   ↓
Refactor only if required
   ↓
Integrate
   ↓
Test
```

1. **Inventory** — list existing local components: modules, agents,
   security components, LLM integrations, experiments. Describe what each
   actually does today (not what it was meant to do).
2. **Classify** — kind of component (parser, agent, security check,
   gateway client, utility, …) and current state (working, experimental,
   abandoned).
3. **Map** — assign each component to a target module of the architecture.
4. **Evaluate** — decide per component (table below). Unmapped components
   get an explicit decision too — nothing silently carried over.
5. **Refactor only if required** — minimal changes to fit the target
   contracts and standards (agent standard, schema-first, prompts as
   code). No opportunistic rewrites.
6. **Integrate** — move into the target module with its tests.
7. **Test** — unit tests plus, where relevant, evals and regression
   artifacts prove the integrated component works in its new home.

## Mapping template

Every inventory decision uses this exact sequence:

```text
Existing Component
→ Target Module
→ Migration Decision
→ Required Changes
→ Required Tests
```

| Existing Component | Target Module | Migration Decision | Required Changes | Required Tests |
| ------------------ | ------------- | ------------------ | ---------------- | -------------- |
| _(filled in the inventory)_ | | | | |

## Decision values

| Value | Meaning |
| ----- | ------- |
| `KEEP` | Usable as-is, stays where it is |
| `MOVE` | Fits the target module, moved unchanged |
| `REFACTOR` | Moved and adapted to contracts/standards |
| `SPLIT` | One component becomes several target modules (or vice versa) |
| `MERGE` | Combined with other components into one module |
| `REPLACE` | Functionality needed, implementation replaced |
| `DEPRECATE` | Not carried over; retired deliberately |

## Rules

- The target architecture decides, not the existing code (ADR-0001).
- Nothing is copied unreviewed.
- Security-relevant components additionally respect
  [../architecture/trust-boundaries.md](../architecture/trust-boundaries.md).
