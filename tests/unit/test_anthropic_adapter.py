"""Offline tests for the temporary direct Anthropic LLM adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import JsonValue

from bidfusion.llm_gateway.anthropic import (
    AnthropicAdapterSettings,
    AnthropicHTTPResult,
    AnthropicLLMAdapter,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.ports import ExternalCapabilityError, LLMPort
from bidfusion.schemas import (
    DataClassification,
    ExternalErrorCode,
    LLMFinishReason,
    LLMRequest,
    ModelCapabilities,
    ModelDataPolicy,
    ModelRequirements,
    ProviderConfig,
    SecretRef,
    StructuredOutputSpec,
)

SECRET_REF = SecretRef(reference="secret://env/BIDFUSION_LLM_API_KEY")
TEST_SECRET = "offline-test-credential"


@dataclass
class RecordingTransport:
    """Record requests and return an inert response without network access."""

    result: AnthropicHTTPResult
    calls: int = 0
    url: str | None = None
    headers: dict[str, str] | None = None
    body: bytes | None = None
    timeout_seconds: float | None = None

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> AnthropicHTTPResult:
        self.calls += 1
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout_seconds = timeout_seconds
        return self.result


def provider_config() -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "endpoint": "https://api.anthropic.com/v1/messages",
            "secret_ref": SECRET_REF,
            "timeout_seconds": 12,
        }
    )


def public_requirements(*, structured_output: bool = False) -> ModelRequirements:
    return ModelRequirements(
        capabilities=ModelCapabilities(structured_output=structured_output),
        data_policy=ModelDataPolicy(
            classification=DataClassification.PUBLIC,
            local_processing_preferred=False,
        ),
    )


def message_body(
    text: str,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 7,
    output_tokens: int = 3,
) -> bytes:
    return json.dumps(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    ).encode()


def adapter_for(transport: RecordingTransport) -> AnthropicLLMAdapter:
    return AnthropicLLMAdapter(
        settings=AnthropicAdapterSettings(
            provider=provider_config(),
            model="claude-sonnet-5",
            max_output_tokens=128,
            route_id="test-route",
        ),
        secret_resolver=EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": TEST_SECRET}),
        transport=transport,
    )


def test_text_request_uses_messages_api_and_returns_owned_contract() -> None:
    transport = RecordingTransport(AnthropicHTTPResult(200, message_body("accepted")))
    adapter = adapter_for(transport)

    response = adapter.generate(
        LLMRequest(
            request_id="REQ-ANTHROPIC-001",
            prompt="Return accepted.",
            requirements=public_requirements(),
        )
    )

    assert isinstance(adapter, LLMPort)
    assert response.request_id == "REQ-ANTHROPIC-001"
    assert response.output_text == "accepted"
    assert response.structured_output is None
    assert response.finish_reason is LLMFinishReason.COMPLETED
    assert response.route_id == "test-route"
    assert response.usage is not None
    assert response.usage.input_tokens == 7
    assert transport.url == "https://api.anthropic.com/v1/messages"
    assert transport.timeout_seconds == 12
    assert transport.headers == {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "user-agent": "bidfusion/0.1",
        "x-api-key": TEST_SECRET,
    }
    assert json.loads(transport.body or b"") == {
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "Return accepted."}],
        "model": "claude-sonnet-5",
    }
    assert TEST_SECRET not in repr(adapter)
    assert TEST_SECRET not in repr(adapter._secret_resolver)  # noqa: SLF001


def test_structured_request_uses_current_output_config_and_parses_json() -> None:
    transport = RecordingTransport(AnthropicHTTPResult(200, message_body('{"status":"ok"}')))
    adapter = adapter_for(transport)
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }

    response = adapter.generate(
        LLMRequest(
            request_id="REQ-ANTHROPIC-002",
            prompt="Return status.",
            requirements=public_requirements(structured_output=True),
            output_spec=StructuredOutputSpec(name="status", json_schema=schema),
        )
    )

    assert response.output_text is None
    assert response.structured_output == {"status": "ok"}
    payload = json.loads(transport.body or b"")
    assert payload["output_config"] == {"format": {"type": "json_schema", "schema": schema}}


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, ExternalErrorCode.INVALID_RESPONSE),
        (401, ExternalErrorCode.AUTHENTICATION_FAILED),
        (403, ExternalErrorCode.AUTHENTICATION_FAILED),
        (408, ExternalErrorCode.TIMEOUT),
        (429, ExternalErrorCode.RATE_LIMITED),
        (500, ExternalErrorCode.UNAVAILABLE),
        (504, ExternalErrorCode.TIMEOUT),
        (529, ExternalErrorCode.UNAVAILABLE),
    ],
)
def test_http_failures_are_normalized_without_provider_body(
    status_code: int,
    expected: ExternalErrorCode,
) -> None:
    provider_body = b'{"error":{"message":"sensitive provider detail"}}'
    adapter = adapter_for(RecordingTransport(AnthropicHTTPResult(status_code, provider_body)))

    with pytest.raises(ExternalCapabilityError) as raised:
        adapter.generate(
            LLMRequest(
                request_id="REQ-ANTHROPIC-003",
                prompt="Synthetic request.",
                requirements=public_requirements(),
            )
        )

    assert raised.value.code is expected
    assert "sensitive" not in str(raised.value)
    assert "sensitive" not in repr(raised.value)


@pytest.mark.parametrize(
    "llm_request",
    [
        LLMRequest(request_id="REQ-POLICY-001", prompt="Default policy is confidential."),
        LLMRequest(
            request_id="REQ-POLICY-002",
            prompt="Internal data.",
            requirements=ModelRequirements(
                data_policy=ModelDataPolicy(
                    classification=DataClassification.INTERNAL,
                    local_processing_preferred=False,
                )
            ),
        ),
        LLMRequest(
            request_id="REQ-POLICY-003",
            prompt="Vision requested.",
            requirements=ModelRequirements(
                capabilities=ModelCapabilities(vision=True),
                data_policy=ModelDataPolicy(
                    classification=DataClassification.PUBLIC,
                    local_processing_preferred=False,
                ),
            ),
        ),
    ],
)
def test_disallowed_egress_is_blocked_before_secret_or_network(
    llm_request: LLMRequest,
) -> None:
    transport = RecordingTransport(AnthropicHTTPResult(200, message_body("unused")))
    adapter = AnthropicLLMAdapter(
        settings=AnthropicAdapterSettings(
            provider=provider_config(),
            model="claude-sonnet-5",
        ),
        secret_resolver=EnvironmentSecretResolver({}),
        transport=transport,
    )

    with pytest.raises(ExternalCapabilityError) as raised:
        adapter.generate(llm_request)

    assert raised.value.code is ExternalErrorCode.POLICY_BLOCKED
    assert transport.calls == 0


def test_missing_secret_is_normalized_and_does_not_call_network() -> None:
    transport = RecordingTransport(AnthropicHTTPResult(200, message_body("unused")))
    adapter = AnthropicLLMAdapter(
        settings=AnthropicAdapterSettings(
            provider=provider_config(),
            model="claude-sonnet-5",
        ),
        secret_resolver=EnvironmentSecretResolver({}),
        transport=transport,
    )

    with pytest.raises(ExternalCapabilityError) as raised:
        adapter.generate(
            LLMRequest(
                request_id="REQ-AUTH-001",
                prompt="Synthetic request.",
                requirements=public_requirements(),
            )
        )

    assert raised.value.code is ExternalErrorCode.AUTHENTICATION_FAILED
    assert transport.calls == 0


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"{}",
        message_body("", stop_reason="end_turn"),
        message_body("ignored", stop_reason="tool_use"),
        message_body("not-json", stop_reason="end_turn"),
    ],
)
def test_malformed_success_is_normalized(body: bytes) -> None:
    adapter = adapter_for(RecordingTransport(AnthropicHTTPResult(200, body)))
    request = LLMRequest(
        request_id="REQ-INVALID-001",
        prompt="Return structured data.",
        requirements=public_requirements(structured_output=True),
        output_spec=StructuredOutputSpec(
            name="result",
            json_schema={"type": "object"},
        ),
    )

    with pytest.raises(ExternalCapabilityError) as raised:
        adapter.generate(request)

    assert raised.value.code is ExternalErrorCode.INVALID_RESPONSE


def test_refusal_and_length_are_distinct_semantics() -> None:
    request = LLMRequest(
        request_id="REQ-STOP-001",
        prompt="Synthetic request.",
        requirements=public_requirements(),
    )
    refusal = adapter_for(
        RecordingTransport(
            AnthropicHTTPResult(200, message_body("declined", stop_reason="refusal"))
        )
    )
    truncated = adapter_for(
        RecordingTransport(
            AnthropicHTTPResult(200, message_body("partial", stop_reason="max_tokens"))
        )
    )

    with pytest.raises(ExternalCapabilityError) as raised:
        refusal.generate(request)
    assert raised.value.code is ExternalErrorCode.POLICY_BLOCKED
    assert truncated.generate(request).finish_reason is LLMFinishReason.LENGTH


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.anthropic.com/v1/messages",
        "https://api.anthropic.com/other",
        "https://example.invalid/v1/messages",
    ],
)
def test_secret_cannot_be_sent_to_an_unapproved_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="endpoint must be"):
        AnthropicAdapterSettings(
            provider=ProviderConfig.model_validate(
                {"endpoint": endpoint, "secret_ref": SECRET_REF}
            ),
            model="claude-sonnet-5",
        )
