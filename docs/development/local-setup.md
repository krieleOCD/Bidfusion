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
references. A future adapter may resolve them from environment values or a
secret store. The foundation needs **no** LLM gateway credentials: no LLM
calls are implemented.

## Notes

- No framework dependencies (no FastAPI, no LangChain, no databases) are
  installed on purpose. Technology choices beyond the foundation are
  conscious, later decisions (ADRs).
- On macOS, use the Homebrew Python if the system Python is older
  than 3.12.
