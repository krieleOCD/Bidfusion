# Provenance

> Important source-derived claims must carry enough information to trace
> them to exact evidence.

Foundation 1.2 makes the trace structure explicit without claiming that a
storage backend or navigation UI exists.

## Contract chain

```text
EvidencedStatement
    normalized_object_ids + sources
        ↓
NormalizedObjectReference
    source_artifacts + sources
        ↓
Focused ExtractionResult ArtifactEnvelope
    input_artifacts
        ↓
CanonicalDocument and source-derived block
    canonical artifact ID + SourceReference
        ↓
Original document ArtifactReference
    document ID + SHA-256 content hash + locator
```

`SourceReference` is defined in `src/bidfusion/schemas/provenance.py`:

```yaml
source:
  bid_id: BID-2026-000123
  document_id: DOC-003
  filename: requirements.pdf
  document_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  canonical_artifact_id: ART-20260727-000002
  locator:
    page: 34
    section_id: SEC-5.2
    paragraph_id: PAR-0042
    text_span:
      start: 0
      end: 47
    bounding_box:       # optional for OCR/vision
      x: 112
      y: 420
      width: 680
      height: 42
      coordinate_space: points
  quote: "24/7 incident response must be provided"
```

Locators can use whole document, page, section, block, paragraph, table,
row, column, cell, text span, or bounding box. Every locator requires at
least one meaningful location; not every field is mandatory.

## Contract-enforced now

- Source-derived canonical sections, paragraphs, tables, cells, figures,
  and footnotes require provenance.
- Extracted requirements, deadlines, entities, formalities, scope, and
  commercial/security/compliance observations require a canonical artifact
  source.
- Normalized object references retain both extraction artifact references
  and original source references.
- Important Working Package claims use `EvidencedStatement`; a global
  evidence bucket cannot substitute for claim-level evidence.
- Artifact envelopes carry schema/producer versions and input hashes.
- Positive capability matches require approved, current governed-knowledge
  evidence snapshots.
- Modeled cross-bid provenance combinations fail validation.

## Runtime-enforced later

- dereference `content_ref` and verify its bytes against `content_hash`;
- verify that normalized IDs actually exist in the referenced dataset;
- verify knowledge snapshots against the authoritative knowledge store;
- preserve lineage during real parsing, extraction, and normalization; and
- provide citation-accuracy evals and source navigation.

## Operationally enforced later

Artifact retention, immutable storage, access control, signing, audit-log
retention, and reviewer identity assurance require deployment controls.
