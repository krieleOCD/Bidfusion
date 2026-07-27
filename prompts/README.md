# Prompts as Code

Prompts are versioned engineering artifacts. They live in the repository,
are reviewed like code, and are never hidden inside business logic.

## Where prompts live

- **Agent-specific prompts** live next to their agent, e.g.
  `agents/<agent_name>/prompts/v1.md` (see
  [docs/agents/agent-standard.md](../docs/agents/agent-standard.md)).
- **Shared / cross-agent prompts** live in this directory:
  `prompts/<name>/v<N>.md`.

## Required metadata

Every production-relevant prompt carries the frontmatter defined in
[TEMPLATE.md](./TEMPLATE.md): name, version, purpose, expected input,
expected output, model requirements, evaluation dataset and evaluation
results.

## Rules

- Prompt changes are code changes: review, version bump, eval re-run.
- No prompt strings embedded in Python business code.
- Model requirements describe *capabilities* (vision, structured output,
  reasoning, context window) — never a concrete provider. Provider and
  model selection is the job of the LLM gateway (ADR-0007).
