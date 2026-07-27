# Contributing

Thanks for contributing to BidFusion. These rules keep the architecture
coherent — they follow directly from the [ADRs](docs/adr/README.md).

## Ground rules

1. **Architecture first.** Changes that affect the architecture start as
   an ADR or a change to an existing one — code follows the decision, not
   the other way around.
2. **Schema first.** Modules exchange typed contracts from
   `src/bidfusion/schemas/`. No ad-hoc JSON between modules (ADR-0005).
3. **Prompts as code.** Prompts are versioned files with metadata, never
   strings in business code. Prompt changes are reviewed like code and
   re-evaluated (see [prompts/README.md](prompts/README.md)).
4. **Security before intelligence.** New document-processing interfaces
   accept the hash-bound clearance contract, never raw paths. Runtime and
   operational enforcement must be implemented before component migration
   (ADR-0002).
5. **No customer data in git.** Ever. See [SECURITY.md](SECURITY.md) and
   [fixtures/README.md](fixtures/README.md).
6. **Honest status.** Do not claim implemented behavior that does not
   exist — in code, docs, or status tables.

## Code standards

- Python ≥ 3.12, src layout, fully typed (`mypy --strict` clean).
- Linted with `ruff` (see `pyproject.toml`).
- Tests with `pytest`; conventions in
  [docs/development/testing.md](docs/development/testing.md).
- Match the surrounding code's style and comment density. Minimal,
  reviewable diffs — no opportunistic cleanups.

## Before you commit

```bash
pytest
ruff check .
ruff format --check .
mypy src/bidfusion scripts tests
python scripts/check_markdown_links.py
uv lock --check
```

## Commits and changes

- Small, focused commits with clear messages (imperative mood, e.g.
  "Add security gate contract").
- One concern per change. Refactors separate from behavior changes.
- No framework or infrastructure dependencies without an ADR
  (no FastAPI, LangChain, Temporal, databases, vector stores, … —
  see ADR-0007 and the roadmap).

## Current phase

**Foundation 1.2 is accepted and frozen.** Component migration now follows
the controlled inventory and decision process in
[component-migration.md](docs/development/component-migration.md). See the
[roadmap](README.md#roadmap) for later phases.
