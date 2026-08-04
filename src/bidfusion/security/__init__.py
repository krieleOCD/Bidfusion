"""Domain B - Security Gate.

"Security before intelligence": no document reaches parsers, OCR,
vision models, extraction agents, or LLMs before it has passed the
security gate. Deterministic preflight produces observations, not a
clearance; final policy remains a separate gate responsibility.
"""

from bidfusion.security.gate_policy import (
    MVP_GATE_POLICY_ID,
    MVP_GATE_POLICY_NAME,
    MVP_GATE_POLICY_VERSION,
    PackageGateDecision,
    PackageGateResult,
    RegisteredArtifacts,
    decide_document,
    decide_package,
)
from bidfusion.security.preflight import (
    ArtifactContentMismatchError,
    DeterministicPreflightScanner,
    PreflightConfig,
    PreflightInputError,
)

__all__ = [
    "MVP_GATE_POLICY_ID",
    "MVP_GATE_POLICY_NAME",
    "MVP_GATE_POLICY_VERSION",
    "ArtifactContentMismatchError",
    "DeterministicPreflightScanner",
    "PackageGateDecision",
    "PackageGateResult",
    "PreflightConfig",
    "PreflightInputError",
    "RegisteredArtifacts",
    "decide_document",
    "decide_package",
]
