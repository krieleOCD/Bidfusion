# ADR-0011: External Capabilities via Ports and Adapters

**Status:** ACCEPTED

## Context

BidFusion will use external or replaceable capabilities for LLM generation,
OCR, and artifact persistence. Provider SDK types, provider selection, and
credential values would couple business code to infrastructure and make
provider changes leak through the domain.

## Decision

> BidFusion owns contracts. Providers are adapters.

**NOW**, Foundation 1.1 defines:

- `LLMPort.generate(LLMRequest) -> LLMResponse`, using the existing
  `ModelRequirements` capability and data-policy contract;
- `OCRPort.extract(OCRRequest) -> OCRResult`, producing normalized,
  source-bound OCR blocks suitable for canonical mapping;
- `ArtifactStore.put(...)` and `ArtifactStore.get(...)` over owned artifact
  envelopes and references;
- one small `ExternalErrorCode` taxonomy and an
  `ExternalCapabilityError` that retains no provider message or SDK
  payload;
- `SecretRef` and strict `ProviderConfig`, which can carry endpoints,
  logical secret references, and non-sensitive settings but cannot carry
  credential values; and
- deterministic test fakes that need no network, credential, or paid
  service.

The ports are structural Python protocols. Business/domain code receives
them as dependencies and must not import a provider SDK or select a
provider directly. A policy block is surfaced as a normalized failure, not
as a successful provider response.

**LATER**, separate implementation work may add concrete adapters, an
enterprise LLM Gateway client, OCR engines, object/local artifact stores,
secret resolution, retries, telemetry, and operational controls. Those
adapters will translate provider requests, responses, and failures at the
boundary. No adapter, provider SDK, registry, factory, plugin framework,
storage backend, or secrets manager is selected by this decision.

## Consequences

- Domain contracts remain stable when providers and deployments change.
- Tests can exercise capability consumers without network access, secrets,
  or cost.
- Credential values stay outside domain models and serialized artifacts.
- Each future adapter must translate to owned contracts and normalize
  errors without passing provider messages across the port.
- Runtime secret resolution, redaction, persistence controls, retries, and
  real integration testing remain explicit later work.
