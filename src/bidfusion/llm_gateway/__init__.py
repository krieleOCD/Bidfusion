"""Model-agnostic LLM gateway client.

Agents declare required capabilities, data policy and cost profile;
the gateway decides model, provider, deployment, fallback and
routing. No provider logic in business agents."""
