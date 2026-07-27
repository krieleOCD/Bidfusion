"""Domain B - Security Gate.

"Security before intelligence": no document reaches parsers, OCR,
vision models, extraction agents, or LLMs before it has passed the
security gate. Verdicts: ALLOW / MANUAL_REVIEW / QUARANTINE / BLOCK.
BLOCK and QUARANTINE stop the normal pipeline for that document."""
