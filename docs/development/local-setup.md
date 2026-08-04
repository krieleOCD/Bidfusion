# Local Setup

BidFusion is local first. Everything runs on your machine; no cloud
resources, no external services required for the foundation.

## Prerequisites

- Python ≥ 3.12 (`python3.12`, `python3.13`, `python3.14`, … all fine)
- git
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
# from the repository root
uv sync --extra dev
```

This installs the `bidfusion` package (src layout) and development tools
exactly from the checked `uv.lock`. Update the lock deliberately with
`uv lock`; do not hand-edit it.

## Verify

```bash
pytest                                   # test suite
ruff check .                             # lint
ruff format --check .                    # format check
mypy src/bidfusion scripts tests         # type check (strict)
python scripts/check_markdown_links.py   # documentation link check
```

## Environment

Local settings come from the environment. Copy `.env.example` to `.env`
and fill in values if needed — `.env` is gitignored and must never be
committed. Domain configuration carries only logical `secret://`
references. The temporary Anthropic adapter resolves its key only at the
adapter boundary; the value never enters `ProviderConfig`, an LLM request,
an exception, or a serialized artifact. Normal setup and automated tests
need **no** LLM credential.

For the temporary direct route, keep these values in `.env`:

```dotenv
BIDFUSION_ANTHROPIC_URL=https://api.anthropic.com/v1/messages
BIDFUSION_ANTHROPIC_MODEL=claude-sonnet-5
BIDFUSION_ANTHROPIC_SECRET_REF=secret://env/BIDFUSION_LLM_API_KEY
BIDFUSION_LLM_API_KEY=<local-secret-value>
```

The model setting belongs to this infrastructure adapter, not to business
code or `LLMRequest`. It can later be replaced with the internal gateway
configuration without changing consumers.

### Explicit synthetic connectivity check

The connectivity check is not part of `pytest` and makes one paid network
request only when invoked explicitly:

```bash
uv run python scripts/check_anthropic_connection.py
```

It loads `.env` without shell evaluation and sends a fixed synthetic,
`PUBLIC` structured-output request. The direct adapter blocks all other
classifications, `local_processing_preferred=True`, artifact inputs, and
vision before secret lookup or network access. Do not substitute real RFP
content into this check.

## Run the local Security Preflight

Place synthetic, public/sanitized, or explicitly approved local documents
in `inbox/`, then run:

```bash
uv run bidfusion-preflight
```

Per-document assessments and a run summary appear in `results/`. Both
directories keep their contents out of Git. The runner performs only the
deterministic preflight slice; it does not run OCR, LLM analysis, complete
gate policy, downstream document processing, or the Anthropic adapter.

See [../../apps/README.md](../../apps/README.md) for all command options.

## Notes

- No framework dependencies (no FastAPI, no LangChain, no databases) are
  installed on purpose. Technology choices beyond the foundation are
  conscious, later decisions (ADRs).
- On macOS, use the Homebrew Python if the system Python is older
  than 3.12.
