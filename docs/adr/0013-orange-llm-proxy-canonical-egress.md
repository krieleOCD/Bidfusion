# ADR-0013: Orange LLM Proxy as the Canonical BidFusion LLM Egress

**Status:** ACCEPTED

## Context

ADR-0007 established that BidFusion is model-agnostic and that business
code never selects a provider or model directly. ADR-0011 established
that BidFusion owns contracts and providers are adapters, and named a
*temporary* direct Anthropic adapter for explicit synthetic/public
connectivity tests, explicitly intended to be replaced by an internal LLM
Gateway adapter.

Orange now operates that internal gateway: an OpenAI-compatible
`/chat/completions` proxy at `https://llmproxy.ai.orange`. This ADR names
it the canonical, long-term LLM egress and defines how BidFusion talks to
it, without disturbing the existing temporary Anthropic route or the
general `LLMPort`/`LLMRequest`/`LLMResponse` contracts.

## Decision

1. BidFusion uses the Orange LLM Proxy as its single intended long-term
   LLM egress. Future production LLM traffic is expected to flow through
   it, not through a directly integrated provider SDK.
2. Business/fach modules must never call an OpenAI, Anthropic, Vertex, or
   other provider SDK directly, and must never construct a
   provider-specific HTTP client. All LLM egress goes through a
   BidFusion-owned port.
3. Provider selection, model selection, guardrail configuration, retry
   behavior, and secret values stay behind that port and its adapter.
   Fach code declares intent (operation, structured response contract,
   policy keys); it never sets base URLs, API keys, free model names, or
   free guardrail parameters.
4. The existing direct Anthropic adapter
   (`src/bidfusion/llm_gateway/anthropic.py`) remains exactly what
   ADR-0007/ADR-0011 already named it: a temporary, narrowly scoped
   adapter for explicit synthetic/public connectivity tests.
5. It is **not** a second production architecture path. New fach code
   must not be built against it going forward — new development targets
   the Orange Proxy port defined in this ADR.
6. It is **not removed** in this slice. Removing or migrating it is a
   separate, deliberate migration decision with its own review, out of
   scope here.
7. This slice introduces a new, narrower, provider-neutral port —
   `LlmClient.complete_structured()` in `src/bidfusion/llm_gateway/port.py`
   — as the foundation for later schema-validated, policy-governed model
   operations. It supports exactly one operation
   (`synthetic_structured_smoke`) routed to exactly one allowed model
   (`openai/gpt-5.4-mini`) in this slice.
8. In this slice, the new port and its Orange Proxy adapter stay
   completely disconnected from the Security Gate, Quarantine,
   `run_package()`, document parsing, extraction, and Working Package
   construction. No business module imports `bidfusion.llm_gateway` as a
   result of this change.
9. `BIDFUSION_LLM_ENABLED` defaults to `false`. Without an explicit
   `true`, no network call to the Orange Proxy is possible — this is
   enforced at settings-construction and adapter-call time, fail-closed.
10. The normal automated test suite stays fully offline. It exercises the
    adapter exclusively through an injected fake transport; the
    session-wide `tests/conftest.py` socket guard, which blocks all
    `AF_INET`/`AF_INET6` socket creation for the whole suite, is left
    unchanged. Real connectivity is reachable only through the standalone
    `scripts/check_orange_proxy_connection.py` script, gated by two
    explicit environment flags, never through `pytest`.
11. No real customer data or RFP content may be sent through this port or
    adapter in this slice. Only synthetic, non-confidential prompts are
    permitted, matching the same posture already established for the
    temporary Anthropic route.
12. The API key configured via `BIDFUSION_LLM_API_KEY` is a
    self-managed developer/service credential, adequate for this
    Foundation slice only. It is not a long-term production identity
    model. A later runtime environment (e.g. a managed service account,
    workload identity, or a secrets-manager-issued short-lived
    credential) requires its own separate decision before production
    traffic flows through this adapter.

### Relationship to the existing general `LLMPort`

`LLMPort`/`LLMRequest`/`LLMResponse` (`src/bidfusion/ports.py`,
`src/bidfusion/schemas/llm.py`) remain unchanged and continue to exist for
backward compatibility with their existing consumers (currently: the
temporary Anthropic adapter and its tests). They are not extended,
narrowed, or reshaped by this ADR. The new `LlmClient` structured port is
additive, not a replacement: it does not implement `LLMPort`, and
`LLMPort` is not implemented in terms of it.

This ADR deliberately does not resolve whether `LLMPort` and `LlmClient`
should later be consolidated, whether one should be deprecated in favor
of the other, or whether they should coexist permanently for different
call shapes (free-text/multimodal-capable vs. narrow schema-validated
operations). That consolidation or deprecation decision is explicitly
left to a future ADR, once real usage of both exists.

**Tracked follow-up.** `LlmClient` is the preferred port for all new
structured model operations going forward; `LLMPort` remains
compatibility-only for its existing consumer and is not a target for new
development. A future consolidation/deprecation ADR is required before
business integration expands beyond this Foundation slice — i.e. before
either port is wired to a real fach module (extraction, review, or
similar), that expansion must be preceded by a decision on whether it
uses `LlmClient`, `LLMPort`, or both, not by default drift toward
whichever happens to be convenient at the time. Once the first real
structured operation is introduced (the point at which `LlmClient` gains
an actual business caller), an AST-based architecture guard equivalent to
`tests/unit/test_llm_gateway_architecture_guards.py`'s existing
`llm_gateway`-import checks may be added to enforce that new fach code
targets `LlmClient` rather than `LLMPort` or a provider SDK; that guard is
not needed while both ports remain unconnected to fach code, so it is not
added in this slice.

## Consequences

- New fach code that needs an LLM has exactly one sanctioned path: the
  Orange Proxy `LlmClient` port. Direct provider SDK usage in fach code
  is an architecture violation, checked by an AST-based import guard in
  `tests/unit/test_llm_gateway_architecture_guards.py`.
- The temporary Anthropic adapter continues to serve its original narrow
  purpose (synthetic/public connectivity checks) without becoming a
  second, competing production integration path. Its removal is deferred
  to a separate migration decision.
- Two independent LLM-related env var families now exist by design:
  `BIDFUSION_ANTHROPIC_*` (temporary direct route) and `BIDFUSION_LLM_*`
  (Orange Proxy, canonical). Their API key variables
  (`BIDFUSION_ANTHROPIC_API_KEY`, `BIDFUSION_LLM_API_KEY`) are distinct
  and must never share a real secret value — they authenticate to
  different destinations.
- Until a future ADR says otherwise, both `LLMPort` and `LlmClient` are
  valid but distinct contracts; new callers should default to
  `LlmClient` for schema-validated operations.
- Production readiness (real service-account credentials, model
  fallback/routing, PII/guardrail policy beyond the two policies defined
  here, full observability) remains explicit future work, not implied by
  this Foundation slice.
