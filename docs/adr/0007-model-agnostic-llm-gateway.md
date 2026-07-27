# ADR-0007: Model-Agnostic LLM Integration

**Status:** ACCEPTED

## Context

An internal LLM gateway already exists. Models, providers and deployments
change faster than business logic; data policies (sensitivity, local
processing) differ per use case. If agents bind to specific providers or
models, every model change becomes a business-code change, and data-policy
enforcement scatters across the codebase.

## Decision

Agents declare **requirements**, never providers or models:

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

`ModelRequirements` contractually represents these needs and rejects
undeclared provider selection. Business code calls the BidFusion-owned
`LLMPort` with `LLMRequest` and receives `LLMResponse`; no provider SDK
object crosses that boundary. The LLM gateway runtime will decide model,
provider, deployment, fallback and routing and enforce the data policy at
the boundary (see
[../architecture/trust-boundaries.md](../architecture/trust-boundaries.md)).
No provider logic in business agents. Concrete adapters and secret
resolution are later work under
[ADR-0011](./0011-external-capabilities-via-ports-and-adapters.md). No LLM
framework dependency is adopted without a dedicated ADR.

## Consequences

- Models can be swapped, upgraded or routed (cost/latency/policy) without
  touching business code.
- Data-policy enforcement is intended to have one runtime choke point.
- Agents must express their needs as capabilities and policies — a small
  design tax per agent.
- Domain code depends only on the owned port and contracts; a future
  adapter may depend on the gateway client.
