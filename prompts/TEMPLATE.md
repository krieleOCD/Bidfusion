---
name: <prompt-name>
version: v1
purpose: <one sentence: what this prompt extracts / decides / produces>
expected_input: <schema or description of the input the prompt receives>
expected_output: <schema or description of the output the prompt must produce>
model_requirements:
  vision: false
  structured_output: true
  reasoning: low        # low | medium | high
  context_window: small # small | medium | large
evaluation_dataset: <path to eval dataset, e.g. evals/datasets/<name>>
evaluation_results: <link or summary of the latest eval run for this version>
---

<The prompt text itself starts here. Keep prompts focused: one bounded
responsibility per prompt. No universal mega-prompts.>
