# ADR-0004: Atomic Agents over Monolithic Agent

**Status:** ACCEPTED

## Context

Business extraction covers many distinct concerns: requirements,
formalities, deadlines, scope, commercial, security, compliance, contract,
entities, submission rules, cross references. A single monolithic agent
with one universal prompt is hard to test, hard to evaluate, hard to
improve — and its failures are opaque.

## Decision

Extraction follows a **fan-out/fan-in pattern** of specialized **atomic
agents**. Each agent has exactly one clearly bounded business
responsibility, its own input/output schemas, versioned prompts, tests and
evals. All agents share one standard structure (see
[../agents/agent-standard.md](../agents/agent-standard.md)). Their results
are merged by the normalization layer, not by the agents themselves.

## Consequences

- Agents can be developed, tested, evaluated and improved independently.
- Parallel execution becomes possible without architectural changes.
- Quality is measurable per concern (per-agent evals) instead of only
  end-to-end.
- More moving parts: the orchestrator and the normalization layer carry
  the coordination and merge complexity.
- No universal mega-prompts — a prompt that tries to do everything is a
  design smell.
