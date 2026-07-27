# ADR-0012: Focused Typed Extraction Results

**Status:** ACCEPTED

## Context

Foundation 1.1 had typed payloads for requirements, deadlines, and
entities, while normalization recognized five additional object kinds.
Extending one universal result with another optional list for every
extractor would couple unrelated nodes and make incomplete execution
indistinguishable from an empty finding set.

## Decision

> Each bounded extraction node produces a bounded typed result.
> Normalization is the explicit fan-in boundary.

Foundation 1.2 defines minimal, source-bound payloads for formality, scope,
commercial, bid-content security, and compliance observations. Each of the
eight extraction streams has a focused result contract sharing only common
job metadata and artifact lineage through `ExtractionResultBase`.

The Foundation 1.1 `ExtractionResult` remains as a compatibility envelope
for its original requirement, deadline, and entity payloads. New extractors
must use focused results; the compatibility envelope will not grow into a
universal mega-envelope.

`NormalizedBidDataset` records expected, completed, failed, and skipped
streams and derives `COMPLETE`, `PARTIAL`, or `FAILED`. This records
execution completeness only. It does not implement scheduling, retries, or
workflow behavior.

## Consequences

- Every extraction node has one bounded, independently versioned output.
- Empty findings remain distinguishable from a stream that did not finish.
- Normalization remains the single deliberate fan-in boundary.
- The five new payloads are source observations, not pricing logic, a
  duplicate Compliance Matrix, or a workflow implementation.
- Existing Foundation 1.1 consumers can migrate from `ExtractionResult`
  without an unrelated immediate break.
- Adding a future extraction stream requires an explicit payload/result
  contract and completeness update.
