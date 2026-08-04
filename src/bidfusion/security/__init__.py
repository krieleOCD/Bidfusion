"""Domain B - Security Gate.

"Security before intelligence": no document reaches parsers, OCR,
vision models, extraction agents, or LLMs before it has passed the
security gate. Deterministic preflight produces observations, not a
clearance; final policy remains a separate gate responsibility.
"""

from bidfusion.security.preflight import (
    ArtifactContentMismatchError,
    DeterministicPreflightScanner,
    PreflightConfig,
    PreflightInputError,
)

__all__ = [
    "ArtifactContentMismatchError",
    "DeterministicPreflightScanner",
    "PreflightConfig",
    "PreflightInputError",
]
