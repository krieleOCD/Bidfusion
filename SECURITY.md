# Security Policy

BidFusion processes confidential customer bid documents. Security is a
design principle of the system, not an afterthought — see
[docs/architecture/trust-boundaries.md](docs/architecture/trust-boundaries.md)
and [ADR-0002](docs/adr/0002-security-before-intelligence.md).

## Reporting a vulnerability

This is currently an internal, local-only project. Report vulnerabilities
and security concerns directly to the BidFusion team through internal
channels. Do **not** file security issues in any future public issue
tracker, and do not include customer data or exploit details in shared
documents.

A dedicated disclosure contact will be added here before any external
release.

## Data safety rules (binding for all contributors)

- **Real customer RFPs, bid documents, prices, contacts, or any customer
  data must NEVER be committed to this repository** — in any directory,
  in any branch, in any commit. Customer data that entered git must be
  treated as an incident (history rewrite is not sufficient — rotated
  credentials and a review are required).
- Test and example data only comes from `fixtures/synthetic/` (generated)
  or `fixtures/safe/` (verifiably sanitized/public). Checklist:
  [fixtures/README.md](fixtures/README.md).
- **Secrets** (API keys, tokens, gateway credentials) are resolved only at
  an adapter boundary from `.env` (gitignored), the process environment, or
  a future secret store — never from a domain model. `.env.example` contains
  empty placeholders and logical `secret://` references only; no credential
  values.
- Domain configuration uses `SecretRef`. `ProviderConfig` deliberately has
  no API-key, token, password, or secret-value field. Resolved values must
  never appear in logs, exceptions, representations, or serialized domain
  artifacts.
- `.gitignore` blocks common secret and customer-data paths; it is a
  safety net, not the rule itself.
- `inbox/` and `results/` are local test-harness directories whose contents
  are ignored by Git. Access, retention, and secure deletion of files placed
  there remain the operator's responsibility.
- The temporary direct Anthropic route accepts only synthetic/public prompt
  requests with explicit external-processing intent. It must not receive
  customer RFP content without a separately approved provider/data-egress
  decision. The inbox preflight runner never invokes this route.

## Architecture-level security

### Contract-enforced in Foundation 1.1

- `SecurityClearedArtifact` binds the exact artifact ID/reference/hash to
  scanner and policy versions and an allowed or audited manual-release
  decision.
- `BLOCK`, `QUARANTINE`, pending manual review, and rejected manual review
  cannot construct the downstream handoff.
- Central artifact, normalization, coverage, compliance, review, and
  working-package contracts reject modeled cross-bid combinations.
- **Data classification** — contracts carry classification
  (`PUBLIC`/`INTERNAL`/`CONFIDENTIAL`/`RESTRICTED`); handling follows it.
- **Governed knowledge** — bid matching reads enterprise knowledge but does
  not mutate it (ADR-0009).
- **External capability boundary** — LLM, OCR, and artifact storage use
  BidFusion-owned ports and models. Provider failures are normalized and
  provider SDK objects cannot enter domain contracts (ADR-0011).
- **Temporary Anthropic egress boundary** — the direct test adapter
  allowlists the Anthropic Messages endpoint and blocks non-`PUBLIC` data,
  local-processing preference, artifacts, and vision before secret lookup
  or network access.

### Runtime-enforced later

- parser/OCR/vision/extraction/LLM APIs accept only the typed clearance;
- storage verifies artifact hashes and enforces per-bid access;
- the internal LLM Gateway applies complete data classification, deployment
  allowlists, routing, and egress policy; and
- logs exclude customer content and resolved secrets.

### Operationally enforced later

Reviewer authorization, scanner isolation, quarantine procedures, access
control, encryption, retention, deletion, secret resolution/rotation,
audit-log retention, monitoring, and incident response require deployment
controls. The contracts do not claim to provide them.

## Scope

This policy covers the repository and local development. Cloud and
production security requirements will be added when deployment is decided
(roadmap phase after foundation review).
