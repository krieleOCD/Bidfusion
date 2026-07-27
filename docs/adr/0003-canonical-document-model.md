# ADR-0003: Canonical Document Model

**Status:** ACCEPTED

## Context

RFP packages are multimodal: PDF, scans, Word, Excel, CSV, PowerPoint,
images, drawings. If every downstream agent parses raw files itself, every
agent pays the parsing cost, parsing quality becomes inconsistent, and
document understanding logic spreads across the codebase.

## Decision

Document Understanding (technical parsing) and Business Extraction
(fachliche extraction) are separate domains. All parsers produce one
shared internal representation — the **canonical document model**:

```text
Document
 ├── Metadata
 ├── Pages
 │    ├── Sections
 │    ├── Paragraphs
 │    ├── Tables
 │    │     ├── Rows
 │    │     └── Cells
 │    ├── Figures
 │    └── Footnotes
 ├── Relationships
 └── Source References
```

Business agents work on this model, not on raw files. Principle:
**parse once, use everywhere.** The contract is `CanonicalDocument` in
`src/bidfusion/schemas/document.py`.

## Consequences

- A parser is written once per format; agents stay format-agnostic.
- The canonical model is a major system boundary: changes to it are
  deliberate, versioned contract changes.
- Source-derived sections, paragraphs, tables, cells, figures, and
  footnotes require source references. Stable block IDs, hierarchy, cell
  spans, OCR confidence, and page/section/table/cell/text/bounding-box
  locators preserve provenance (ADR-0006).
- Some format-specific detail may be lost in normalization; parsers keep
  the raw parse output as an intermediate artifact (ADR-0008) so nothing
  is unrecoverable.
