# ADR-0002: Security Before Intelligence

**Status:** ACCEPTED

## Context

RFP packages are untrusted input: unknown files, potentially manipulated
or corrupted content, archives, executables, macros, embedded objects,
malware, dangerous payloads — and, in an LLM-driven system, prompt
injection and hidden instructions. If any processing (parsing, OCR, vision
models, extraction agents, LLM calls) touches a file before security
checks, the checks are decorative.

## Decision

The security gate is a **core component of the pipeline**, not an optional
extraction agent. Every document passes the gate before any intelligence
touches it. Verdicts: `ALLOW` / `MANUAL_REVIEW` / `QUARANTINE` / `BLOCK`.
On `BLOCK` or `QUARANTINE`, the normal pipeline stops for that document.
The downstream handoff is `SecurityClearedArtifact`, which binds a raw
`ArtifactReference`, its SHA-256 content hash, scanner and policy versions,
decision timestamp, and `SecurityResult`. A `MANUAL_REVIEW` result remains
pending until an audited actor releases or rejects it. `BLOCK`,
`QUARANTINE`, pending review, and rejected review cannot construct the
handoff contract. The gate fails closed: scanner errors and unknown types
escalate, they never silently pass.

## Consequences

- The hash-bound handoff and verdict semantics are contract-enforced and
  adversarially tested in `src/bidfusion/schemas/security.py`.
- Parser APIs accepting only this handoff, authorization, process isolation,
  and privileged reviewer identity verification require later runtime and
  operational enforcement.
- Processing of suspicious files is delayed by design; a privileged
  quarantine workflow handles exceptions.
- Documented in [../architecture/trust-boundaries.md](../architecture/trust-boundaries.md).
