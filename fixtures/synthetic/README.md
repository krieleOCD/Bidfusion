# Synthetic RFP Fixtures

Fully invented test data for the local walking skeleton. Regenerate with
`python scripts/generate_synthetic_fixtures.py`. PDF fixtures are
byte-deterministic; the XLSX fixture is content-deterministic (ZIP entry
timestamps vary, so tests compare content, not bytes).

## `rfp-minimal/` — clean package (full pipeline)

| File | Expected content |
| ---- | ---------------- |
| `rfp-invitation.pdf` | Page 1: title, customer, submission deadline `2026-09-30 17:00`, Q&A deadline `2026-09-11 12:00`, portal submission, PDF format rule, signature requirement. Page 2: `REQ-P1`/`REQ-P2` (MUST), `REQ-P3` (SHOULD), `REQ-P4` (MAY), `REQ-P5` (deliberately unclear, no modality), contract start `2027-01-01`. |
| `requirements-matrix.xlsx` | Sheet `Requirements`: header + `REQ-X1` (MUST), `REQ-X2` (SHOULD), `REQ-X3` (MUST, exact duplicate of `REQ-P2` for dedup). Sheet `Timeline`: site-visit and presentation dates (unique, no conflicts, no formulas). Sheet `Formalities`: PDF format and XLSX price-sheet rules. |
| `notes.txt` | `REQ-T1` (MUST) and one late-submission formality. |

## `rfp-blocked/` — package-level BLOCK

`payload.js` (blocked extension → preflight FAIL CRITICAL) plus a clean
`cover.txt`. The package gate must block the whole package; `cover.txt`
must never reach a parser.

## `rfp-review/` — package-level REVIEW_REQUIRED

`declared-encrypted.pdf` declares `/Encrypt` (preflight FAIL HIGH →
MANUAL_REVIEW) plus a clean `note.txt`. Pending review stops the package.

## `rfp-unsupported/` — parser-level unsupported

`blank-scan.pdf` is structurally valid, passes preflight, but contains no
extractable text. Document understanding must report it as
review-required; the run must never present it as a successful, complete
extraction.

## `rfp-quality-review/` — quality gate REVIEW_REQUIRED

`mixed-scan.pdf` (page 1: `REQ-Q1` MUST, `REQ-Q2` SHOULD, plus one
uppercase-MUST sentence *without* a `REQ-` prefix; page 2 deliberately
blank) and `quality-matrix.xlsx` (`REQ-QX` repeats the `REQ-Q2` text with
a conflicting `MUST` modality; sheet `Calc` holds a formula without a
cached value). Both files clear the security gate, but the quality gate
must end in `REVIEW_REQUIRED` with a review package instead of a working
package.
