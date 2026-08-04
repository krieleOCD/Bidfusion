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
