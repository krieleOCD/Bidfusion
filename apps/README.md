# Applications

## Local Security Preflight

The first runnable application is a local, provider-free inbox runner for
the deterministic Security Gate preflight.

```bash
# From the repository root:
cp /path/to/synthetic-or-approved-document.pdf inbox/
uv run bidfusion-preflight
```

Input files may be nested below `inbox/`. The runner leaves them unchanged
and writes:

- one `*.preflight.json` assessment per document;
- one timestamped `*.summary.json`; and
- `results/latest-summary.json` for convenient inspection.

Custom paths and bid identity are supported:

```bash
uv run bidfusion-preflight \
  --inbox /path/to/local/inbox \
  --results /path/to/local/results \
  --bid-id BID-2026-000123 \
  --max-file-size-mb 100
```

Exit code `0` means every deterministic check completed with only `PASS`
or `NOT_APPLICABLE`. Exit code `2` means at least one document requires
attention or could not be processed. This is not a final Security Gate
verdict and never creates `ALLOW` or `SecurityClearedArtifact`.

The checked-in `inbox/` and `results/` directories contain only `.gitkeep`.
Their working contents are ignored by Git because they may contain
confidential documents or local assessment metadata.

## Local MVP Pipeline (walking skeleton)

The second runnable application processes one local RFP package end to
end on synthetic or explicitly approved local data:

```bash
uv run bidfusion-run \
  --input /path/to/local/package \
  --output /path/to/local/results \
  --bid-id BID-2026-000123 \
  --process
```

`--input` and `--output` are required, must be explicit, distinct local
directories, and must never be the repository `inbox/` or `results/`
harness directories — the CLI rejects them. Without `--process` the run
stops after the security stage; per-document assessments, security
results, and the package gate decision are still written below
`<output>/<bid>/<run>/`.

Downstream parsing (text-based PDF, XLSX, TXT/CSV), rule-based
extraction, normalization, the quality gate, and the Working Package
(JSON + Markdown) run only when the versioned MVP package gate policy
(`bidfusion-mvp-local-gate:0.1.0`) decides `CLEARED`: every registered
document must be explicitly `ALLOW` and match the exact registered
artifact. One `BLOCK` blocks the whole package; any error, unknown
outcome, quarantine, pending manual review, or intake rejection keeps
the whole package in review. There is no partial processing of a package
in this MVP.

### Quality gate and review package

After extraction and normalization the versioned quality gate
(`bidfusion-mvp-quality-gate:0.1.0`) checks measurable coverage signals
(parser warnings, empty pages, uncached XLSX formulas, empty or failed
extraction streams, obligations the rule set could not capture,
unresolved conflicts, provenance consistency):

- `ACCEPTABLE` → normal `working-package/…` output, exit code `0`.
- `REVIEW_REQUIRED` → **no** working package; instead
  `review-package/review-package.{json,md}`, unambiguously marked
  `NOT A COMPLETE BID WORKING PACKAGE`, containing reasons, warnings,
  affected documents/sources, and everything reliably detected (always
  with sources). Exit code `2`.
- `FAILED` → neither package; only quality and run status. Exit code `2`.

### Real-sample lock (non-production)

Full processing (`--process`) is allowed for `fixtures/synthetic/`
inputs only. Other local inputs additionally require
`--authorized-non-production-test`, which confirms an authorized,
**non-production** test run. The flag never bypasses the security or
quality gates, never unlocks the repository `inbox/`/`results/`
directories (equal or below, via absolute, relative, `..`, or symlinked
paths), and outputs must always live **outside any repository
checkout**. This is not a production release: there is still no
production security gate, no malware signatures, no isolated no-network
parser container, no CPU/RAM/timeout limits, no approved quarantine
process, no retention/deletion rule, and no release for real customer
data.

### Confidential outputs

All run outputs are written owner-only (directories `0700`, files
`0600`) and atomically. These artifacts contain **full or partial source
text** and must be handled like the input documents: `canonical/*`
(full text), `extraction/*`, `normalized/*`, `working-package/*`, and
`review-package/*` (extracted text and quotes). `security/*`,
`inventory/*`, `quality/*`, and `run-summary.json` carry filenames,
hashes, and findings metadata only. `integrity-manifest.json` holds
whole-file digests; `verify_run_integrity()` re-checks them.

Exit code `0` means the run finished its permitted depth without
findings (security-only or fully completed with `ACCEPTABLE` quality).
Exit code `2` means the package was blocked, requires review (security
or quality), or failed; details are in
`<output>/<bid>/<run>/run-summary.json`.
