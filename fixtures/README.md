# Fixtures

Test and evaluation fixtures for BidFusion.

## Policy

**Real customer RFPs, bid documents, or any customer data must NEVER be
added to this repository** — not even "just for a quick local test".
`.gitignore` blocks the usual suspect paths, but the rule itself is the
first line of defense.

Two kinds of fixtures are allowed:

- `synthetic/` — artificially generated dummy RFPs and documents. These
  will later form the benchmark dataset for evaluations
  (see [docs/development/evals.md](../docs/development/evals.md)).
- `safe/` — sanitized, verifiably non-confidential samples (e.g. publicly
  available tender documents or hand-crafted minimal files).

## Checklist before adding a fixture

1. Is it synthetic or verifiably public/sanitized? If unsure: do not add it.
2. Does it contain real company names, prices, contacts, or internal data?
   If yes: do not add it.
3. Is it small enough for git? Large binary samples belong in artifact
   storage, not in the repository.
