# Golden Dataset — MTD Knowledge Pilot

The first real internal knowledge area in BidFusion: the Managed Threat
Detection (MTD) service documentation set, inventoried and partially
ingested as **Domain K — Golden Dataset** (ADR-0009). This document is
the binding description of the pilot slice: its data flow, its
deterministic classification tables, its trust model, and its limits.

## What this pilot is — and is not

**Is:** a local, read-only inventory of a real internal document set; a
security-gated, deterministic ingestion of the pilot document families
through the existing reviewed parsers; rule-extracted capability claims
that are explicitly unverified; and a deterministic keyword matching of
five synthetic demo requirements — all rendered in the product shell
under `INTERNAL KNOWLEDGE PILOT` labels.

**Is not:** a validated knowledge base. Nothing in this slice makes a
claim true. No LLM, no network, no connector, no embeddings, and no
customer RFP data are involved anywhere in the golden path.

## Data flow (ADR-0009: separate from the bid path)

```text
Golden Knowledge Source   (local directory, read-only, never in git)
  → Knowledge Intake      (inventory: hash, deterministic classification)
    → Safe Parsing        (real preflight + gate, existing reviewed parsers)
      → Normalized Knowledge   (KnowledgeDocument with sections)
        → Capability Claims    (rule-based, EXTRACTED_UNVERIFIED)
          → Provenance         (source_id, hash, version, locator)
            → Human Review Status (REQUIRED until a person confirms)
```

The golden path creates **no BidRun and no RFP artifact**. Architecture
guard tests (`tests/unit/test_golden_architecture_guards.py`) enforce
that `bidfusion.golden_dataset` never imports `bidrun`, `local_ui`,
`llm_gateway`, `intake`, `orchestration`, `working_package`, or any
network/subprocess module.

## Where data lives

- **Sources:** a local directory supplied to
  `scripts/run_golden_mtd_ingestion.py` via `--source-dir`. Read
  strictly read-only. Never committed; never hardcoded in the
  repository.
- **Artifacts:** the gitignored runtime store
  `runtime/golden_dataset/` (`inventory.json`, `documents/GKD-*.json`,
  `claims.json`, `matches.json`), created owner-only via
  `bidfusion.shared.secure_io`.
- **Repository:** only code, schemas, tests with synthetic fixtures,
  and this documentation. Serialized artifacts are path-free by
  contract: `KnowledgeSource` has no path field at all, and the
  `source_id -> local path` mapping exists only in memory during a run.

## Deterministic classification tables

Classification reads **filenames only** — never content, never a model.
Anything not matched by a table is `unknown`; nothing is guessed. The
authoritative implementation is
`src/bidfusion/golden_dataset/classification.py`; the tables below must
stay in sync with it.

### Document families (filename prefix before the first dash)

| Prefix | document_type |
| ------ | ------------- |
| SD | service_description |
| QA | qa_technology_guidance |
| SAP | service_activation_procedure |
| SI | service_instruction |
| CL | checklist |
| CP | customer_presentation |
| DS | datasheet |
| OV | overview |
| PO | pricing_commercial |
| OE | offering_estimate |
| OH | operational_handbook |
| SC | service_catalogue |
| SOW | statement_of_work |

A file without a known prefix whose name contains "statement of work"
(case-insensitive) is a `statement_of_work`. Everything else — including
the observed `SR` prefix — is `unknown`.

### Technology (ordered token table, first casefolded substring wins)

| Token | technology |
| ----- | ---------- |
| microsoft defender xdr, microsoft 365 defender, defender xdr | microsoft_defender_xdr |
| microsoft sentinel, sentinel | microsoft_sentinel |
| xsiam | palo_alto_xsiam |
| cortex, palo alto, paloaltonetworks | palo_alto_cortex_xdr |
| splunk | splunk |
| vectra | vectra |
| ebonding | itsm_ebonding |
| [isolation], threat response | managed_threat_response |
| microsoft (bare) | microsoft_generic |
| managed threat detection, mtd | generic_mtd |
| (no match) | unknown |

Deliberate ordering: `xsiam` beats `cortex`, so a Cortex-to-XSIAM
migration document is classified by its target platform, and the bare
`microsoft` fallback only fires when no specific Microsoft platform is
named — a document that names none gets `microsoft_generic` rather than
a guessed platform.

### Version

Recognized version markers: `v2026.2.1`, `v2.1`, `v.2.1`, `v0.x`
(literal `x` preserved), and a bare trailing `3.1`. No marker → no
version, never an invented one.

## Trust model

Three levels are kept apart end to end and labeled in the UI:

1. **Real internal sources** — inventory records of real files
   (`KnowledgeSource`, hash-bound).
2. **Machine-extracted statements** — `KnowledgeDocument` sections and
   `CapabilityClaim`s. Claims are born `EXTRACTED_UNVERIFIED` with
   `human_review_status = REQUIRED`; the contract forbids constructing a
   claim as human-confirmed and forbids claims without evidence
   (`no evidence → no claim`).
3. **Human-confirmed knowledge** — reachable exclusively through
   `confirm_claim(claim, reviewer=...)`. Nothing in this pilot calls it.

The five matching requirements are **synthetic demo inputs** defined in
`bidfusion.golden_dataset.matching.SYNTHETIC_DEMO_REQUIREMENTS` and are
labeled `SYNTHETIC DEMO INPUT` wherever they render.

## Security boundaries

Before any content is parsed, every source passes the **real**
`DeterministicPreflightScanner` and gate policy (size bounds, MIME and
extension checks, archive limits, macro detection, embedded objects,
PDF JavaScript/embedded files, encryption) — fail closed per source. A
gate verdict other than `ALLOW` means the source stays inventoried with
`INGESTION_FAILED` and a static, operator-safe reason; parser exception
text never leaves the ingestion service.

**Pilot boundary — bid-shaped parser contracts.** The reviewed parsers
require a `SecurityClearedArtifact`, which carries bid-shaped IDs. The
golden path reuses the parsers unchanged under a reserved internal
namespace (`GOLDEN_SCOPE_*` in `golden_dataset/ingestion.py`); those
values exist only during the parser call and cannot appear in golden
artifacts, which have no field for them. The clean cut — a
domain-neutral parsing core — is future work, not part of this slice.

**Pilot boundary — parser assurance.** The parsers are reviewed and
tested against synthetic fixtures. Running them over real internal
documents is exactly what this pilot does, but that is not a
"production safe" claim, and the UI never makes one.

## Known limits of this slice

- PPTX is inventoried but not parsed (`PARSE_UNSUPPORTED`); no new
  parser was built.
- Only the pilot document families (SD, QA, SAP, SI, OV, SC, SOW) are
  deep-ingested; pricing/commercial and remaining families are
  inventoried and marked `NOT_SELECTED`.
- DOCX headers, footers, footnotes, and text boxes are outside the
  parser's content model; XLSX provenance is sheet plus cell range;
  plain-text locators would be normalized line positions. Sections
  whose parser yields no locator are marked, and the document becomes
  `PROVENANCE_PARTIAL` — locators are never invented.
- Claim extraction and matching are fixed keyword rules — a pilot
  demonstration of the evidence discipline, not a semantic capability.
