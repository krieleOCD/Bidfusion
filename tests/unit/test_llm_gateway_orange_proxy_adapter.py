"""Offline tests for the Orange Proxy adapter: HTTP shape, errors, retries.

Every test injects a fake ``OrangeProxyTransport`` — no real socket is ever
opened (``tests/conftest.py`` also blocks AF_INET/AF_INET6 sockets for the
whole suite as a structural backstop).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.orange_proxy import (
    OrangeProxyAdapter,
    OrangeProxyHTTPResult,
    _resolved_api_key_is_safe,
)
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    GuardrailStatus,
    LlmClient,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    SchemaValidationStatus,
    StructuredLlmOperation,
    StructuredLlmRequest,
    SyntheticGatewayResult,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import OrangeProxySettings, load_orange_proxy_settings
from bidfusion.schemas.common import DataClassification
from bidfusion.schemas.llm import LLMFinishReason

TEST_SECRET = "offline-test-orange-key"


def enabled_settings(**overrides: str) -> OrangeProxySettings:
    env = {
        "BIDFUSION_LLM_ENABLED": "true",
        "BIDFUSION_LLM_API_KEY": TEST_SECRET,
        **overrides,
    }
    return load_orange_proxy_settings(env)


def disabled_settings() -> OrangeProxySettings:
    return load_orange_proxy_settings({"BIDFUSION_LLM_ENABLED": "false"})


def secret_resolver() -> EnvironmentSecretResolver:
    return EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": TEST_SECRET})


def request(
    *,
    request_id: str = "REQ-ORANGE-001",
    guardrail_policy_key: GuardrailPolicyKey = GuardrailPolicyKey.DEFAULT,
    model_policy_key: ModelPolicyKey = ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
    operation: StructuredLlmOperation = StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
    max_output_tokens: int | None = None,
) -> StructuredLlmRequest:
    return StructuredLlmRequest(
        operation=operation,
        messages=(LlmMessage(role=LlmMessageRole.USER, content="Return a synthetic object."),),
        response_schema_name="synthetic_gateway_result",
        request_id=request_id,
        data_classification=DataClassification.PUBLIC,
        model_policy_key=model_policy_key,
        guardrail_policy_key=guardrail_policy_key,
        max_output_tokens=max_output_tokens,
    )


def success_body(
    *,
    content: str = '{"title":"accepted","items":[],"confidence":0.9}',
    finish_reason: str = "stop",
    model: str = "openai/gpt-5.4-mini",
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
) -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-test",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    ).encode()


def success_result(
    *,
    content: str = '{"title":"accepted","items":[],"confidence":0.9}',
    finish_reason: str = "stop",
    model: str = "openai/gpt-5.4-mini",
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
) -> OrangeProxyHTTPResult:
    body = success_body(
        content=content,
        finish_reason=finish_reason,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


def guardrail_blocked_result() -> OrangeProxyHTTPResult:
    body = json.dumps({"error": {"type": "guardrail_blocked"}}).encode()
    return OrangeProxyHTTPResult(status_code=400, content_type="application/json", body=body)


def result_with_raw_usage(
    usage: object,
    *,
    content: str = '{"title":"accepted","items":[],"confidence":0.9}',
) -> OrangeProxyHTTPResult:
    """Build a 200 response with an arbitrary, possibly-malformed usage block."""
    body = json.dumps(
        {
            "id": "chatcmpl-test",
            "model": "openai/gpt-5.4-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }
    ).encode()
    return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


@dataclass
class RecordedTransportCall:
    url: str
    headers: dict[str, str]
    body: bytes
    timeout_seconds: float
    request_id: str


@dataclass
class SequencedTransport:
    """Fake OrangeProxyTransport returning/raising a scripted sequence."""

    outcomes: list[OrangeProxyHTTPResult | LlmGatewayError] = field(default_factory=list)
    calls: list[RecordedTransportCall] = field(default_factory=list)

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        request_id: str,
    ) -> OrangeProxyHTTPResult:
        self.calls.append(
            RecordedTransportCall(
                url=url,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
                request_id=request_id,
            )
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, LlmGatewayError):
            raise outcome
        return outcome


@dataclass
class RecordingSleeper:
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class ZeroClock:
    def monotonic_ms(self) -> int:
        return 0


def adapter_for(
    transport: SequencedTransport,
    *,
    settings: OrangeProxySettings | None = None,
    sleeper: RecordingSleeper | None = None,
) -> OrangeProxyAdapter:
    return OrangeProxyAdapter(
        settings=settings if settings is not None else enabled_settings(),
        secret_resolver=secret_resolver(),
        transport=transport,
        clock=ZeroClock(),
        sleeper=sleeper if sleeper is not None else RecordingSleeper(),
    )


# --- fail-closed / disabled -------------------------------------------------


def test_adapter_is_a_valid_llm_client() -> None:
    adapter = adapter_for(SequencedTransport(outcomes=[success_result()]))
    assert isinstance(adapter, LlmClient)


def test_disabled_gateway_raises_llm_disabled_without_any_transport_call() -> None:
    transport = SequencedTransport(outcomes=[])
    adapter = OrangeProxyAdapter(
        settings=disabled_settings(),
        secret_resolver=secret_resolver(),
        transport=transport,
        clock=ZeroClock(),
        sleeper=RecordingSleeper(),
    )

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.LLM_DISABLED
    assert transport.calls == []


def test_model_policy_key_mismatched_with_operation_is_a_request_policy_violation() -> None:
    # Only one (operation, model_policy_key) pair is constructible through
    # the public contract today, so a real mismatch can't happen via normal
    # validated construction. This test protects the adapter's
    # defense-in-depth check by forcing an inconsistent value past the
    # frozen-model guard directly — exactly the "can't happen" case the
    # check exists for.
    transport = SequencedTransport(outcomes=[])
    adapter = adapter_for(transport)
    bad_request = request()
    object.__setattr__(bad_request, "model_policy_key", "not_the_expected_key")

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=bad_request, response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION
    assert transport.calls == []


def test_settings_model_drifted_from_policy_is_model_not_allowed() -> None:
    # Defense-in-depth: only one allowed model exists today, so settings and
    # policy can't genuinely disagree through normal construction. Force the
    # drift directly past the frozen-dataclass guard to prove the adapter
    # still catches it rather than silently trusting settings.
    transport = SequencedTransport(outcomes=[])
    settings = enabled_settings()
    object.__setattr__(settings, "default_model", "openai/gpt-4o")
    adapter = OrangeProxyAdapter(
        settings=settings,
        secret_resolver=secret_resolver(),
        transport=transport,
        clock=ZeroClock(),
        sleeper=RecordingSleeper(),
    )

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.MODEL_NOT_ALLOWED
    assert transport.calls == []


# --- HTTP request shape ------------------------------------------------------


def test_sends_a_post_to_chat_completions_with_expected_headers() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    call = transport.calls[0]
    assert call.url == "https://llmproxy.ai.orange/chat/completions"
    assert call.headers["content-type"] == "application/json"
    assert call.headers["authorization"] == f"Bearer {TEST_SECRET}"
    assert call.request_id == "REQ-ORANGE-001"


def test_authorization_header_is_never_exposed_via_repr_of_the_adapter() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert TEST_SECRET not in repr(adapter)


def test_payload_uses_the_policy_resolved_model() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    payload = json.loads(transport.calls[0].body)
    assert payload["model"] == "openai/gpt-5.4-mini"


def test_payload_carries_the_user_messages_in_order() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)
    req = StructuredLlmRequest(
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        messages=(
            LlmMessage(role=LlmMessageRole.SYSTEM, content="be terse"),
            LlmMessage(role=LlmMessageRole.USER, content="go"),
        ),
        response_schema_name="synthetic_gateway_result",
        request_id="REQ-ORANGE-002",
        data_classification=DataClassification.PUBLIC,
        model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
    )

    adapter.complete_structured(request=req, response_type=SyntheticGatewayResult)

    payload = json.loads(transport.calls[0].body)
    tail = payload["messages"][-2:]
    assert tail == [{"role": "system", "content": "be terse"}, {"role": "user", "content": "go"}]


def test_default_guardrail_policy_omits_the_guardrails_field() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    payload = json.loads(transport.calls[0].body)
    assert "guardrails" not in payload


def test_synthetic_prompt_injection_probe_sets_the_guardrails_field() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    adapter.complete_structured(
        request=request(guardrail_policy_key=GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE),
        response_type=SyntheticGatewayResult,
    )

    payload = json.loads(transport.calls[0].body)
    assert payload["guardrails"] == [{"name": "speleoguards_llamapromptguard", "threshold": 0.8}]


# --- structured success + validation -----------------------------------------


def test_valid_structured_response_is_parsed_and_validated() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = adapter_for(transport)

    result = adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert result.validated_output == SyntheticGatewayResult(
        title="accepted", items=(), confidence=0.9
    )
    assert result.finish_reason is LLMFinishReason.COMPLETED
    assert result.schema_validation_status is SchemaValidationStatus.VALID
    assert result.guardrail_status is GuardrailStatus.NOT_APPLIED
    assert result.attempts == 1
    assert result.usage is not None
    assert result.usage.total_tokens == 8
    assert result.model_reported == "openai/gpt-5.4-mini"


def test_length_finish_reason_maps_to_length() -> None:
    transport = SequencedTransport(outcomes=[success_result(finish_reason="length")])
    adapter = adapter_for(transport)

    result = adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert result.finish_reason is LLMFinishReason.LENGTH


def test_unexpected_finish_reason_is_invalid_provider_response() -> None:
    transport = SequencedTransport(outcomes=[success_result(finish_reason="tool_calls")])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


def test_invalid_json_content_is_schema_validation_failed_not_retried() -> None:
    transport = SequencedTransport(outcomes=[success_result(content="not-json")])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED
    assert len(transport.calls) == 1


def test_missing_required_field_is_schema_validation_failed() -> None:
    body = '{"items":[],"confidence":0.5}'  # missing "title"
    transport = SequencedTransport(outcomes=[success_result(content=body)])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED


def test_extra_field_in_structured_content_is_schema_validation_failed() -> None:
    body = '{"title":"x","items":[],"confidence":0.5,"unexpected":true}'
    transport = SequencedTransport(outcomes=[success_result(content=body)])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED


def test_out_of_range_confidence_is_schema_validation_failed() -> None:
    body = '{"title":"x","items":[],"confidence":5.0}'
    transport = SequencedTransport(outcomes=[success_result(content=body)])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED


def test_schema_validation_failure_never_returns_a_partial_result() -> None:
    transport = SequencedTransport(outcomes=[success_result(content="not-json")])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError):
        result = adapter.complete_structured(
            request=request(), response_type=SyntheticGatewayResult
        )
        del result  # never reached; failure must raise, not return


# --- malformed HTTP envelope --------------------------------------------------


def test_wrong_content_type_is_invalid_provider_response() -> None:
    result = OrangeProxyHTTPResult(status_code=200, content_type="text/html", body=b"<html></html>")
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


def test_invalid_json_body_is_invalid_provider_response() -> None:
    result = OrangeProxyHTTPResult(
        status_code=200, content_type="application/json", body=b"{not json"
    )
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


def test_missing_choices_is_invalid_provider_response() -> None:
    body = json.dumps({"id": "x", "model": "openai/gpt-5.4-mini"}).encode()
    result = OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


def test_missing_message_content_is_invalid_provider_response() -> None:
    body = json.dumps(
        {
            "choices": [{"index": 0, "message": {"role": "assistant"}, "finish_reason": "stop"}],
        }
    ).encode()
    result = OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


def test_unexpected_response_shape_is_invalid_provider_response() -> None:
    body = json.dumps({"completely": "unexpected"}).encode()
    result = OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


# --- error mapping and retries ------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE),
        (401, LlmGatewayErrorCode.AUTHENTICATION_FAILED),
        (403, LlmGatewayErrorCode.AUTHORIZATION_FAILED),
    ],
)
def test_non_retryable_status_codes_raise_once_without_retry(
    status_code: int, expected_code: LlmGatewayErrorCode
) -> None:
    result = OrangeProxyHTTPResult(
        status_code=status_code, content_type="application/json", body=b"{}"
    )
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is expected_code
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_retryable_status_codes_retry_up_to_the_configured_maximum(status_code: int) -> None:
    failing = OrangeProxyHTTPResult(
        status_code=status_code, content_type="application/json", body=b"{}"
    )
    transport = SequencedTransport(outcomes=[failing, failing, success_result()])
    sleeper = RecordingSleeper()
    adapter = adapter_for(
        transport, settings=enabled_settings(BIDFUSION_LLM_MAX_RETRIES="2"), sleeper=sleeper
    )

    result = adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert result.attempts == 3
    assert len(transport.calls) == 3
    assert len(sleeper.slept) == 2


def test_retries_never_exceed_one_plus_max_retries() -> None:
    failing = OrangeProxyHTTPResult(status_code=503, content_type="application/json", body=b"{}")
    transport = SequencedTransport(outcomes=[failing, failing, failing])
    adapter = adapter_for(transport, settings=enabled_settings(BIDFUSION_LLM_MAX_RETRIES="2"))

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.PROVIDER_UNAVAILABLE
    assert len(transport.calls) == 3


def test_timeout_from_transport_is_retried() -> None:
    timeout_error = LlmGatewayError(LlmGatewayErrorCode.TIMEOUT)
    transport = SequencedTransport(outcomes=[timeout_error, success_result()])
    adapter = adapter_for(transport)

    result = adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert result.attempts == 2


def test_connection_error_from_transport_is_retried() -> None:
    connection_error = LlmGatewayError(LlmGatewayErrorCode.PROVIDER_UNAVAILABLE)
    transport = SequencedTransport(outcomes=[connection_error, success_result()])
    adapter = adapter_for(transport)

    result = adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert result.attempts == 2


def test_guardrail_block_raises_guardrail_blocked_without_retry() -> None:
    transport = SequencedTransport(outcomes=[guardrail_blocked_result()])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.GUARDRAIL_BLOCKED
    assert len(transport.calls) == 1


def test_backoff_is_bounded_and_deterministic_without_real_sleep() -> None:
    failing = OrangeProxyHTTPResult(status_code=429, content_type="application/json", body=b"{}")
    transport = SequencedTransport(outcomes=[failing, failing, success_result()])
    sleeper = RecordingSleeper()
    adapter = adapter_for(
        transport, settings=enabled_settings(BIDFUSION_LLM_MAX_RETRIES="2"), sleeper=sleeper
    )

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert sleeper.slept == sorted(sleeper.slept)  # non-decreasing backoff
    assert all(0 < delay <= 4.0 for delay in sleeper.slept)  # bounded, no real wait


# --- secret handling -----------------------------------------------------------


def test_secret_resolution_failure_maps_to_authentication_failed() -> None:
    transport = SequencedTransport(outcomes=[])
    adapter = OrangeProxyAdapter(
        settings=enabled_settings(),
        secret_resolver=EnvironmentSecretResolver({}),  # key absent at call time
        transport=transport,
        clock=ZeroClock(),
        sleeper=RecordingSleeper(),
    )

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.AUTHENTICATION_FAILED
    assert transport.calls == []


def test_secret_never_appears_in_a_provider_error_translation() -> None:
    body = json.dumps({"error": {"message": f"invalid key {TEST_SECRET} rejected"}}).encode()
    result = OrangeProxyHTTPResult(status_code=401, content_type="application/json", body=body)
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert TEST_SECRET not in str(raised.value)
    assert TEST_SECRET not in repr(raised.value)


def test_request_id_is_preserved_on_every_error_path() -> None:
    result = OrangeProxyHTTPResult(status_code=401, content_type="application/json", body=b"{}")
    transport = SequencedTransport(outcomes=[result])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(
            request=request(request_id="REQ-DIAGNOSTIC-001"), response_type=SyntheticGatewayResult
        )

    assert raised.value.request_id == "REQ-DIAGNOSTIC-001"


# --- M1: malformed provider usage is normalized, never a raw ValidationError ---

_USAGE_SENTINEL = "sk-FAKE-USAGE-SENTINEL-DO-NOT-LEAK"


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 99}, id="mismatch"
        ),
        pytest.param(
            {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 0}, id="negative"
        ),
        pytest.param(
            {"prompt_tokens": 1.5, "completion_tokens": 1, "total_tokens": 2}, id="non_integer"
        ),
        pytest.param({"prompt_tokens": 1}, id="missing_fields"),
        pytest.param(
            {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 99,
                "note": _USAGE_SENTINEL,
            },
            id="extra_structure_with_sentinel",
        ),
    ],
)
def test_malformed_usage_is_normalized_to_invalid_provider_response(usage: object) -> None:
    transport = SequencedTransport(outcomes=[result_with_raw_usage(usage)])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(
            request=request(request_id="REQ-USAGE-001"), response_type=SyntheticGatewayResult
        )

    error = raised.value
    assert type(error) is LlmGatewayError
    assert error.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE
    assert error.retryable is False
    assert error.request_id == "REQ-USAGE-001"
    assert len(transport.calls) == 1  # one attempt only, never retried
    for surface in (str(error), repr(error), " ".join(str(a) for a in error.args)):
        assert _USAGE_SENTINEL not in surface
        assert "sk-FAKE" not in surface


def test_malformed_usage_output_never_reaches_captured_stdio(
    capsys: pytest.CaptureFixture[str],
) -> None:
    usage = {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 99,
        "note": _USAGE_SENTINEL,
    }
    transport = SequencedTransport(outcomes=[result_with_raw_usage(usage)])
    adapter = adapter_for(transport)

    with pytest.raises(LlmGatewayError):
        adapter.complete_structured(
            request=request(request_id="REQ-USAGE-002"), response_type=SyntheticGatewayResult
        )

    captured = capsys.readouterr()
    assert _USAGE_SENTINEL not in captured.out
    assert _USAGE_SENTINEL not in captured.err


# --- M2: malformed resolved API key never reaches header construction ---------
#
# ``EnvironmentSecretResolver.resolve()`` already calls ``.strip()`` on the
# resolved value (existing, unchanged behavior — see secrets.py), so a bad
# character placed at the very start/end of the key never reaches this
# adapter via that particular resolver: it is already gone by the time
# ``complete_structured`` sees it. The integration cases below therefore
# place CR/LF/tab *inside* the key so they survive resolution and actually
# exercise the new check end-to-end; pure leading/trailing whitespace is
# covered directly against ``_resolved_api_key_is_safe`` further down,
# independent of any particular resolver's own stripping behavior.

_KEY_SENTINEL = "sk-FAKE-SUPER-SECRET-SENTINEL"
_MALFORMED_KEYS = [
    pytest.param(_KEY_SENTINEL[:10] + "\r" + _KEY_SENTINEL[10:], id="embedded_cr"),
    pytest.param(_KEY_SENTINEL[:10] + "\n" + _KEY_SENTINEL[10:], id="embedded_lf"),
    pytest.param(_KEY_SENTINEL[:10] + "\r\n" + _KEY_SENTINEL[10:], id="embedded_crlf"),
    pytest.param(_KEY_SENTINEL[:10] + "\t" + _KEY_SENTINEL[10:], id="embedded_tab"),
    pytest.param(_KEY_SENTINEL[:10] + " " + _KEY_SENTINEL[10:], id="embedded_space"),
    pytest.param(_KEY_SENTINEL[:10] + "\x00" + _KEY_SENTINEL[10:], id="nul"),
    pytest.param(_KEY_SENTINEL[:10] + "\x7f" + _KEY_SENTINEL[10:], id="del"),
    pytest.param(_KEY_SENTINEL[:10] + "é" + _KEY_SENTINEL[10:], id="non_ascii"),
    pytest.param(_KEY_SENTINEL + ("x" * 600), id="excessive_length"),
]


class ExplodingTransportM2:
    """Fails the test loudly if the malformed key ever reaches the transport."""

    def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
        raise AssertionError("malformed API key must be rejected before any transport call")


@pytest.mark.parametrize("malformed_key", _MALFORMED_KEYS)
def test_malformed_resolved_api_key_is_rejected_before_any_transport_call(
    malformed_key: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = OrangeProxyAdapter(
        settings=enabled_settings(),
        secret_resolver=EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": malformed_key}),
        transport=ExplodingTransportM2(),
        clock=ZeroClock(),
        sleeper=RecordingSleeper(),
    )

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(
            request=request(request_id="REQ-KEY-001"), response_type=SyntheticGatewayResult
        )

    error = raised.value
    assert type(error) is LlmGatewayError
    assert error.code is LlmGatewayErrorCode.AUTHENTICATION_FAILED
    assert error.retryable is False
    assert error.request_id == "REQ-KEY-001"

    captured = capsys.readouterr()
    for surface in (
        str(error),
        repr(error),
        " ".join(str(a) for a in error.args),
        captured.out,
        captured.err,
    ):
        assert _KEY_SENTINEL not in surface
        assert malformed_key not in surface


def test_well_formed_resolved_api_key_is_accepted() -> None:
    transport = SequencedTransport(outcomes=[success_result()])
    adapter = OrangeProxyAdapter(
        settings=enabled_settings(),
        secret_resolver=EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": "a-normal-token-123"}),
        transport=transport,
        clock=ZeroClock(),
        sleeper=RecordingSleeper(),
    )

    adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param(_KEY_SENTINEL + "\r", id="trailing_cr"),
        pytest.param(_KEY_SENTINEL + "\n", id="trailing_lf"),
        pytest.param(_KEY_SENTINEL + "\r\n", id="trailing_crlf"),
        pytest.param(_KEY_SENTINEL + "\t", id="trailing_tab"),
        pytest.param(" " + _KEY_SENTINEL, id="leading_whitespace"),
        pytest.param(_KEY_SENTINEL + " ", id="trailing_whitespace"),
        pytest.param(_KEY_SENTINEL[:10] + " " + _KEY_SENTINEL[10:], id="embedded_space"),
        pytest.param(_KEY_SENTINEL + "\x00", id="nul"),
        pytest.param(_KEY_SENTINEL + "\x7f", id="del"),
        pytest.param(_KEY_SENTINEL + "é", id="non_ascii"),
        pytest.param(_KEY_SENTINEL + ("x" * 600), id="excessive_length"),
    ],
)
def test_resolved_api_key_safety_check_rejects_every_malformed_class(value: str) -> None:
    assert _resolved_api_key_is_safe(value) is False


def test_resolved_api_key_safety_check_accepts_a_normal_token() -> None:
    assert _resolved_api_key_is_safe("a-normal-token-123") is True


# --- M2: transport-level ValueError defense-in-depth ---------------------------


class ValueErrorRaisingTransport:
    """Simulates a transport implementation whose header construction fails."""

    def __init__(self, message: str) -> None:
        self._message = message
        self.calls = 0

    def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
        self.calls += 1
        raise ValueError(self._message)


def test_transport_value_error_mentioning_authorization_is_authentication_failed() -> None:
    sentinel_message = (
        "Invalid header value b'Bearer synthetic-super-secret'; Authorization rejected"
    )
    transport = ValueErrorRaisingTransport(sentinel_message)
    adapter = adapter_for(transport)  # type: ignore[arg-type]

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(
            request=request(request_id="REQ-VALUEERR-001"), response_type=SyntheticGatewayResult
        )

    error = raised.value
    assert error.code is LlmGatewayErrorCode.AUTHENTICATION_FAILED
    assert error.retryable is False
    assert error.request_id == "REQ-VALUEERR-001"
    assert transport.calls == 1  # no retry
    assert "synthetic-super-secret" not in str(error)
    assert "synthetic-super-secret" not in repr(error)
    assert "Authorization" not in str(error)


def test_transport_value_error_unrelated_to_authorization_is_invalid_configuration() -> None:
    transport = ValueErrorRaisingTransport("unicode encoding failure while building the request")
    adapter = adapter_for(transport)  # type: ignore[arg-type]

    with pytest.raises(LlmGatewayError) as raised:
        adapter.complete_structured(request=request(), response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.INVALID_CONFIGURATION
    assert raised.value.retryable is False
