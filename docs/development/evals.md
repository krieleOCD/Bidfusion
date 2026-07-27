# Evaluations

LLM components are not only unit-tested — they are **evaluated**. Unit
tests check code; evals measure the quality of model-driven behavior over
datasets.

## Structure

```text
evals/
├── datasets/    # evaluation datasets
├── metrics/     # metric definitions (catalog in metrics/README.md)
└── runners/     # eval runners (executing prompts/agents against datasets)
```

## Metrics (perspective)

Requirement recall and precision, classification accuracy, deadline
accuracy, metadata accuracy, citation accuracy, table extraction accuracy,
cross reference accuracy, hallucination rate, capability matching
accuracy. The catalog lives in
[../../evals/metrics/README.md](../../evals/metrics/README.md); precise
definitions land with the first runner.

## Datasets

- Benchmark datasets are built from **synthetic dummy RFPs**
  (`fixtures/synthetic/`) with known ground truth.
- **Human corrections** (persisted `HumanReview` records) become eval
  data over time — the system learns from its reviewers.
- Real customer data is never used in datasets.

## Prompts and evals

Every production prompt declares its evaluation dataset and latest results
in its frontmatter (see [../../prompts/README.md](../../prompts/README.md)).
A prompt change without an eval re-run is an incomplete change.

## Status

Prepared structure only — no runners or datasets exist in the foundation
phase, and no LLM calls are implemented.
