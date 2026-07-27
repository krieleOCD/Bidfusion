"""Contract tests for provider-independent external capability boundaries."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from bidfusion.ports import (
    ArtifactStore,
    ExternalCapabilityError,
    LLMPort,
    OCRPort,
)
from bidfusion.schemas import (
    ArtifactEnvelope,
    ArtifactProducer,
    ArtifactReference,
    ArtifactType,
    ExternalErrorCode,
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ModelCapabilities,
    ModelRequirements,
    OCRBlock,
    OCRRequest,
    OCRResult,
    ProviderConfig,
    SecretRef,
    SecurityClearedArtifact,
    SecurityResult,
    SecurityVerdict,
    SourceLocator,
    SourceReference,
    StructuredOutputSpec,
)

ROOT = Path(__file__).resolve().parents[2]
BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260727-0001"
DOCUMENT_ID = "DOC-003"
NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)


def raw_artifact() -> ArtifactReference:
    """Build a stable raw source reference for contract tests."""
    content_hash = sha256(b"source document").hexdigest()
    return ArtifactReference(
        artifact_id="ART-20260727-000001",
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref="artifacts/ART-20260727-000001",
        content_hash=content_hash,
    )


def cleared_source() -> SecurityClearedArtifact:
    """Build an ALLOW-bound handoff accepted by Document Understanding."""
    artifact = raw_artifact()
    result = SecurityResult(
        bid_id=BID_ID,
        document_id=DOCUMENT_ID,
        artifact=artifact,
        content_hash=artifact.content_hash,
        verdict=SecurityVerdict.ALLOW,
        scanner="fake-scanner",
        scanner_version="1.0.0",
        policy_version="2026.07",
        decided_at=NOW,
    )
    return SecurityClearedArtifact(
        artifact=artifact,
        document_id=DOCUMENT_ID,
        security_result=result,
    )


class FakeLLM:
    """Deterministic, cost-free LLMPort implementation for tests."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.output_spec is not None:
            return LLMResponse(
                request_id=request.request_id,
                structured_output={"answer": "accepted"},
                finish_reason=LLMFinishReason.COMPLETED,
                route_id="fake",
                usage=LLMUsage(input_tokens=3, output_tokens=1),
            )
        return LLMResponse(
            request_id=request.request_id,
            output_text="accepted",
            finish_reason=LLMFinishReason.COMPLETED,
            route_id="fake",
            usage=LLMUsage(input_tokens=3, output_tokens=1),
        )


class FakeOCR:
    """Deterministic, credential-free OCRPort implementation for tests."""

    def extract(self, request: OCRRequest) -> OCRResult:
        source = request.source.artifact
        text = "Service availability must be 99.9%."
        block = OCRBlock(
            block_id="BLOCK-001",
            order=0,
            text=text,
            confidence=0.99,
            source=SourceReference(
                bid_id=source.bid_id,
                document_id=request.source.document_id,
                filename="requirements.pdf",
                document_hash=source.content_hash,
                locator=SourceLocator(page=1, block_id="BLOCK-001"),
            ),
        )
        envelope = ArtifactEnvelope(
            artifact_id="ART-20260727-000002",
            bid_id=source.bid_id,
            run_id=source.run_id,
            artifact_type=ArtifactType.OCR_RESULT,
            schema_version="1.0.0",
            content_ref="artifacts/ART-20260727-000002",
            content_hash=sha256(text.encode()).hexdigest(),
            producer=ArtifactProducer(component="fake-ocr", version="1.0.0"),
            input_artifacts=(source,),
            created_at=NOW,
        )
        return OCRResult(
            artifact=envelope,
            bid_id=source.bid_id,
            document_id=request.source.document_id,
            source_artifact=source,
            blocks=(block,),
            detected_language="en",
        )


class FakeArtifactStore:
    """In-memory, network-free ArtifactStore implementation for tests."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[ArtifactReference, bytes]] = {}

    def put(self, envelope: ArtifactEnvelope, content: bytes) -> ArtifactReference:
        if sha256(content).hexdigest() != envelope.content_hash:
            raise ExternalCapabilityError(
                ExternalErrorCode.INVALID_RESPONSE,
            )
        reference = envelope.as_reference()
        self._entries[reference.artifact_id] = (reference, content)
        return reference

    def get(self, reference: ArtifactReference) -> bytes:
        entry = self._entries.get(reference.artifact_id)
        if entry is None:
            raise ExternalCapabilityError(
                ExternalErrorCode.UNAVAILABLE,
            )
        stored_reference, content = entry
        if stored_reference != reference:
            raise ExternalCapabilityError(
                ExternalErrorCode.INVALID_RESPONSE,
            )
        return content


def test_ports_depend_only_on_bidfusion_owned_contracts() -> None:
    llm_types = get_type_hints(LLMPort.generate)
    ocr_types = get_type_hints(OCRPort.extract)
    store_types = {
        *get_type_hints(ArtifactStore.put).values(),
        *get_type_hints(ArtifactStore.get).values(),
    }

    assert llm_types == {"request": LLMRequest, "return": LLMResponse}
    assert ocr_types == {"request": OCRRequest, "return": OCRResult}
    for annotation in store_types:
        assert getattr(annotation, "__module__", "") in {"bidfusion.schemas.artifact", "builtins"}

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["pydantic>=2.7,<3"]


def test_fakes_satisfy_ports_without_network_or_credentials() -> None:
    assert isinstance(FakeLLM(), LLMPort)
    assert isinstance(FakeOCR(), OCRPort)
    assert isinstance(FakeArtifactStore(), ArtifactStore)

    request = LLMRequest(
        request_id="REQ-CALL-001",
        prompt="Return an acceptance object.",
        requirements=ModelRequirements(capabilities=ModelCapabilities(structured_output=True)),
        output_spec=StructuredOutputSpec(
            name="acceptance",
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        ),
    )
    response = FakeLLM().generate(request)

    assert type(response) is LLMResponse
    assert response.structured_output == {"answer": "accepted"}
    assert response.model_dump().keys().isdisjoint({"provider", "api_key", "sdk_response"})


def test_llm_request_cannot_select_a_provider_or_model() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        LLMRequest.model_validate(
            {
                "request_id": "REQ-CALL-001",
                "prompt": "Summarize.",
                "provider": "external-vendor",
                "model": "vendor-model",
            }
        )


def test_llm_structured_output_must_be_declared_as_a_capability() -> None:
    with pytest.raises(ValidationError, match="structured_output capability"):
        LLMRequest(
            request_id="REQ-CALL-002",
            prompt="Return an object.",
            output_spec=StructuredOutputSpec(
                name="answer",
                json_schema={"type": "object"},
            ),
        )


def test_ocr_returns_owned_normalized_blocks_with_source_lineage() -> None:
    source = cleared_source()
    result = FakeOCR().extract(OCRRequest(source=source, language_hints=["en"]))

    assert type(result) is OCRResult
    assert type(result.blocks[0]) is OCRBlock
    assert result.source_artifact == source.artifact
    assert result.artifact.input_artifacts == (source.artifact,)
    assert result.blocks[0].source.canonical_artifact_id is None
    assert result.blocks[0].source.locator.page == 1


def test_artifact_store_preserves_owned_reference_and_exact_bytes() -> None:
    content = b"normalized OCR output"
    source = raw_artifact()
    envelope = ArtifactEnvelope(
        artifact_id="ART-20260727-000003",
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_type=ArtifactType.OCR_RESULT,
        schema_version="1.0.0",
        content_ref="artifacts/ART-20260727-000003",
        content_hash=sha256(content).hexdigest(),
        producer=ArtifactProducer(component="fake-ocr", version="1.0.0"),
        input_artifacts=(source,),
        created_at=NOW,
    )
    store = FakeArtifactStore()

    with pytest.raises(ExternalCapabilityError) as missing:
        store.get(source)
    assert missing.value.code is ExternalErrorCode.UNAVAILABLE

    reference = store.put(envelope, content)

    assert reference == envelope.as_reference()
    assert store.get(reference) == content


def test_external_failures_use_small_normalized_taxonomy() -> None:
    assert {code.value for code in ExternalErrorCode} == {
        "unavailable",
        "timeout",
        "rate_limited",
        "authentication_failed",
        "invalid_response",
        "policy_blocked",
    }
    failure = ExternalCapabilityError(
        ExternalErrorCode.TIMEOUT,
    )
    assert failure.code is ExternalErrorCode.TIMEOUT
    assert str(failure) == "external capability failed: timeout"
    assert repr(failure) == "ExternalCapabilityError('external capability failed: timeout')"


def test_provider_config_serializes_references_but_no_secret_fields() -> None:
    config = ProviderConfig.model_validate(
        {
            "endpoint": "https://gateway.example.invalid",
            "secret_ref": SecretRef(reference="secret://env/BIDFUSION_LLM_GATEWAY_API_KEY"),
            "timeout_seconds": 15,
        }
    )
    dumped = config.model_dump(mode="json")
    serialized = json.dumps(dumped)

    assert "secret://env/BIDFUSION_LLM_GATEWAY_API_KEY" in serialized
    assert set(dumped) == {"endpoint", "secret_ref", "timeout_seconds"}
    assert dumped["secret_ref"] == {"reference": "secret://env/BIDFUSION_LLM_GATEWAY_API_KEY"}
    assert all(field not in dumped for field in ("api_key", "token", "password", "secret_value"))


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"endpoint": "not-a-url"},
        {"endpoint": "https://user:secret@gateway.example.invalid"},
        {"endpoint": "https://gateway.example.invalid?api_key=secret"},
        {"endpoint": "https://gateway.example.invalid", "timeout_seconds": 0},
        {
            "endpoint": "https://gateway.example.invalid",
            "secret_ref": {"reference": "actual-secret-value"},
        },
        {"endpoint": "https://gateway.example.invalid", "api_key": "actual-secret-value"},
        {
            "endpoint": "https://gateway.example.invalid",
            "secret_value": "actual-secret-value",
        },
    ],
)
def test_malformed_or_secret_bearing_provider_config_is_rejected(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate(invalid)


def test_repository_secret_boundaries_are_explicit() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "\n.env\n" in f"\n{gitignore}"
    assert ".env.*" in gitignore
    assert "!.env.example" in gitignore
    assert "BIDFUSION_LLM_GATEWAY_API_KEY=" not in env_example
    assert (
        "BIDFUSION_LLM_GATEWAY_SECRET_REF=secret://env/BIDFUSION_LLM_GATEWAY_API_KEY"
    ) in env_example
