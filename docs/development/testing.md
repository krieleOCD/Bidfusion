# Testing

## Test taxonomy

| Directory | Purpose |
| --------- | ------- |
| `tests/unit/` | Fast, isolated tests of contracts and pure logic |
| `tests/integration/` | Tests across module boundaries (e.g. parser → canonical model) |
| `tests/pipeline/` | End-to-end pipeline tests on synthetic fixtures |
| `tests/security/` | Security gate tests, isolation and data-safety tests |
| `tests/regression/` | Pinned known-good artifacts; changes must be deliberate |

`tests/unit/` pins the Foundation contracts. `tests/security/` exercises the
deterministic preflight slice with synthetic in-memory documents. Together
they cover strict schemas and typed IDs; security assessment, verdict,
review, and hash-binding semantics; artifact lineage; canonical and
claim-level provenance; requirement modality/category; normalized fan-in;
cross-bid rejection; governed knowledge evidence; processing/business
separation; compliance; and distinct AI validation versus business
approval.

## Running tests

```bash
pytest                # whole suite
pytest tests/unit     # one layer
```

## Fixture policy

Tests only use `fixtures/synthetic/` (generated dummy data) or
`fixtures/safe/` (verifiably sanitized/public samples). **Real customer
documents are never used in tests** — see
[../../fixtures/README.md](../../fixtures/README.md) and
[../../SECURITY.md](../../SECURITY.md).

## Conventions

- Tests are fully typed; mypy strict covers `tests/`.
- LLM calls are always mocked or replaced by fixtures in unit and
  integration tests — tests never hit a real model.
- The temporary Anthropic adapter has an injectable transport and is fully
  exercised offline. The separate
  `scripts/check_anthropic_connection.py` command is an explicit, synthetic
  operator check; it is never collected by `pytest`.
- When a bug is fixed, the failing case becomes a test.
- LLM-component quality is measured by evals, not only by tests — see
  [evals.md](./evals.md).
