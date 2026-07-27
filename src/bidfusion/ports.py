"""BidFusion-owned ports for external capabilities.

Concrete providers are future adapters. Business and domain code depend only
on these structural contracts and normalized failure semantics.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bidfusion.schemas.artifact import ArtifactEnvelope, ArtifactReference
from bidfusion.schemas.external import ExternalErrorCode
from bidfusion.schemas.llm import LLMRequest, LLMResponse
from bidfusion.schemas.ocr import OCRRequest, OCRResult


class ExternalCapabilityError(RuntimeError):
    """Provider failure exposed without retaining messages or SDK payloads."""

    def __init__(self, code: ExternalErrorCode) -> None:
        self.code = code
        super().__init__(f"external capability failed: {code.value}")


@runtime_checkable
class LLMPort(Protocol):
    """Provider-neutral text or multimodal generation capability."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a normalized response or raise ExternalCapabilityError."""
        ...


@runtime_checkable
class OCRPort(Protocol):
    """Provider-neutral OCR capability."""

    def extract(self, request: OCRRequest) -> OCRResult:
        """Extract normalized OCR blocks or raise ExternalCapabilityError."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Minimal immutable artifact-content boundary."""

    def put(self, envelope: ArtifactEnvelope, content: bytes) -> ArtifactReference:
        """Persist exact bytes and return the corresponding owned reference."""
        ...

    def get(self, reference: ArtifactReference) -> bytes:
        """Return exact bytes for an immutable owned reference."""
        ...
