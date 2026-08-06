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
BIDFUSION_ANTHROPIC_SECRET_REF=secret://env/BIDFUSION_ANTHROPIC_API_KEY
BIDFUSION_ANTHROPIC_API_KEY=<local-secret-value>
```

`BIDFUSION_ANTHROPIC_API_KEY` belongs exclusively to this temporary direct
route. It is a different credential from `BIDFUSION_LLM_API_KEY` (Orange LLM
Proxy, see below) and the two must never be set to the same real secret
value.

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

## Orange LLM Proxy Gateway (ADR-0013)

The Orange LLM Proxy is BidFusion's canonical, long-term LLM egress — see
[ADR-0013](../adr/0013-orange-llm-proxy-canonical-egress.md) and
[`src/bidfusion/llm_gateway/`](../../src/bidfusion/llm_gateway/). Business
code depends only on the provider-neutral `LlmClient` port
(`bidfusion.llm_gateway.port`); provider, model, guardrail, retry, and
secret details stay inside `OrangeProxyAdapter`. This Foundation slice is
**not** wired into `run_package()`, parsing, extraction, the Security Gate,
or Quarantine, and it must never see real RFP or customer content.

Supported environment variables, all optional with safe defaults, `enabled`
defaulting to `false`:

```dotenv
BIDFUSION_LLM_PROVIDER=orange_proxy
BIDFUSION_LLM_BASE_URL=https://llmproxy.ai.orange
BIDFUSION_LLM_API_KEY=<local-secret-value>
BIDFUSION_LLM_DEFAULT_MODEL=openai/gpt-5.4-mini
BIDFUSION_LLM_TIMEOUT_SECONDS=60
BIDFUSION_LLM_MAX_RETRIES=2
BIDFUSION_LLM_ENABLED=false
BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=false
```

`BIDFUSION_LLM_API_KEY` belongs exclusively to the Orange Proxy gateway —
it is a different credential from `BIDFUSION_ANTHROPIC_API_KEY` above, and
the two must never be set to the same real secret value. Without an
explicit `BIDFUSION_LLM_ENABLED=true`, no network call to the proxy is
possible; settings are still validated fail-closed even while disabled.
Only `openai/gpt-5.4-mini` is an allowed model in this slice, and only one
operation (`synthetic_structured_smoke`) exists. Nothing is read from a
`.env` file automatically anywhere in this gateway — export the variables
in your shell/process environment, or load `.env` yourself before running
a script.

Guardrails: by default no `guardrails` field is sent (team/key guardrails
configured on the proxy apply). An optional
`synthetic_prompt_injection_probe` guardrail policy key requests the
`speleoguards_llamapromptguard` guardrail at threshold `0.8`. No other
guardrail names or thresholds are reachable from a request.

### Explicit synthetic connectivity check

Like the Anthropic check above, this is not part of `pytest` and only runs
for real when **both** flags are explicitly `true`:

```bash
BIDFUSION_LLM_ENABLED=true BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=true \
  uv run python scripts/check_orange_proxy_connection.py
```

It sends one short, synthetic, non-confidential prompt and prints only
safe metadata (request ID, operation, model, status, token counts if
available, duration, schema-validation outcome) — never the prompt, the
response body, the API key, or the `Authorization` header. It reads no
files and never touches `inbox/` or `results/`.

### Known limitations

- The Orange Proxy's exact guardrail-block error-response shape is not
  conclusively documented; detection uses a narrow, synthetic-fixture-backed
  convention and falls back to a generic error rather than guessing.
- Structured output uses a strict JSON-only prompt protocol validated with
  Pydantic, not a provider-native `response_format`, since the latter was
  not reliably documented at the time of writing.
- No automatic model fallback, routing, or multi-model support exists yet
  — exactly one model is allowed.

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
