# Atomic Agent Standard

Every atomic agent in BidFusion follows the same structure and rules.
The goal: anyone opening an agent immediately understands it.

## The seven questions

Opening an agent must answer, without reading its code line by line:

1. **What does it do?** — one bounded business responsibility
2. **What does it get?** — typed input schema
3. **What does it return?** — typed output schema
4. **What dependencies does it have?** — declared, minimal
5. **Which model capabilities does it need?** — declared for the LLM gateway
6. **How is it tested?** — unit tests with fixtures
7. **How is its quality measured?** — evals with datasets and metrics

## Directory layout

```text
agents/
└── requirement_extractor/
    ├── README.md          # answers questions 1–7, in prose
    ├── agent.py           # the agent implementation
    ├── config.yaml        # model requirements, data policy, cost profile
    ├── schemas/
    │   ├── input.py       # Pydantic input contract
    │   └── output.py      # Pydantic output contract
    ├── prompts/
    │   └── v1.md          # versioned prompt (prompts as code)
    ├── tests/             # unit tests (no LLM calls; gateway mocked)
    ├── evals/             # agent-specific eval definitions
    └── fixtures/          # agent-local synthetic fixtures
```

## Rules

- **One responsibility.** If an agent needs a second concern, it becomes
  a second agent. No universal mega-prompts.
- **Schema-first I/O.** Input and output are Pydantic contracts
  (ADR-0005); agents never emit ad-hoc JSON.
- **Model-agnostic.** `config.yaml` declares capabilities, data policy
  and cost profile; the LLM gateway routes (ADR-0007). No provider SDKs,
  no model names in agent code.
- **Prompts as code.** Prompts are versioned files with metadata
  (see [../../prompts/README.md](../../prompts/README.md)), never strings
  buried in Python.
- **Provenance-preserving.** Outputs carry source references and
  extraction metadata (ADR-0006).
- **Security-respecting.** Target agent APIs receive canonical artifacts
  descended from `SecurityClearedArtifact` (ADR-0002); they never accept
  raw file paths. Runtime enforcement arrives with the agents.
- **Honest about uncertainty.** `UNKNOWN` / `UNCLEAR` /
  `REQUIRES_REVIEW` beat invented answers.
- **No retries inside agents.** Retry and failure handling are
  orchestrator concerns; agents report status and errors.

## Status

This standard is the *target*. Agents are implemented from Phase 5
onwards; migrated components are refactored into this shape during
Phase 4 (see [../development/component-migration.md](../development/component-migration.md)).
