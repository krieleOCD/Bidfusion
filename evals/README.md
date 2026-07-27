# Evaluations

LLM components are not only unit-tested — they are **evaluated**. This
directory holds the evaluation foundation: datasets, metrics and runners.

See [docs/development/evals.md](../docs/development/evals.md) for the full
concept.

- `datasets/` — evaluation datasets, built from `fixtures/synthetic/`
  dummy RFPs and, later, persisted human corrections.
- `metrics/` — metric definitions (requirement recall/precision, citation
  accuracy, hallucination rate, ...).
- `runners/` — eval runners that execute prompts/agents against datasets
  and compute metrics.

Evals are currently **prepared structure only** — no LLM calls are
implemented in the foundation phase.
