"""Model-output failure cases for the pilot operation, fully offline.

Every case drives the real ``OrangeProxyAdapter`` with a scripted fake
transport and the pilot response schema. Expected outcome: the stable
gateway error taxonomy — and never raw model text, header material, or
provider body fragments in the public error message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter, OrangeProxyHTTPResult
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import load_orange_proxy_settings
from bidfusion.rfp_api_pilot.contracts import LlmRequirementNormalization
from bidfusion.schemas.common import DataClassification

TEST_SECRET = "offline-test-orange-key"

VALID_CONTENT = json.dumps(
    {
        "schema_version": "1.0.0",
        "requirement_id": "REQ-000001",
        "requirement_type": "obligation",
        "mandatory_status": "mandatory",
        "technology": "microsoft_sentinel",
        "capability": "24_7_monitoring",
        "constraints": [],
        "conditions": [],
        "exclusions": [],
        "normalization_status": "normalized",
        "confidence_band": "HIGH",
        "ambiguity_flags": [],
        "rationale": "Sentinel obligation.",
    }
)


@dataclass
class SequencedTransport:
    outcomes: list[OrangeProxyHTTPResult | LlmGatewayError] = field(default_factory=list)
    calls: int = 0

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        request_id: str,
    ) -> OrangeProxyHTTPResult:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, LlmGatewayError):
            raise outcome
        return outcome


class NoSleep:
    def sleep(self, seconds: float) -> None:  # noqa: ARG002 - protocol signature
        return None


class ZeroClock:
    def monotonic_ms(self) -> int:
        return 0


def adapter_for(transport: SequencedTransport) -> OrangeProxyAdapter:
    settings = load_orange_proxy_settings(
        {"BIDFUSION_LLM_ENABLED": "true", "BIDFUSION_LLM_API_KEY": TEST_SECRET}
    )
    return OrangeProxyAdapter(
        settings=settings,
        secret_resolver=EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": TEST_SECRET}),
        transport=transport,
        clock=ZeroClock(),
        sleeper=NoSleep(),
    )


def pilot_request() -> StructuredLlmRequest:
    return StructuredLlmRequest(
        operation=StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION,
        messages=(LlmMessage(role=LlmMessageRole.USER, content="One synthetic requirement text."),),
        response_schema_name="llm_requirement_normalization",
        request_id="REQ-PILOT-FAILURES-001",
        data_classification=DataClassification.ANONYMIZED_INTERNAL_PILOT,
        model_policy_key=ModelPolicyKey.RFP_REQUIREMENT_NORMALIZATION,
        guardrail_policy_key=GuardrailPolicyKey.DEFAULT,
    )


def http_ok(content: str) -> OrangeProxyHTTPResult:
    body = json.dumps(
        {
            "model": "openai/gpt-5.4-mini",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
        }
    ).encode()
    return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


def call(transport: SequencedTransport) -> LlmGatewayError:
    adapter = adapter_for(transport)
    with pytest.raises(LlmGatewayError) as failure:
        adapter.complete_structured(
            request=pilot_request(), response_type=LlmRequirementNormalization
        )
    return failure.value


# --- payload-shape failures --------------------------------------------------


def test_valid_payload_succeeds_as_baseline() -> None:
    adapter = adapter_for(SequencedTransport(outcomes=[http_ok(VALID_CONTENT)]))
    result = adapter.complete_structured(
        request=pilot_request(), response_type=LlmRequirementNormalization
    )
    assert result.validated_output.requirement_id == "REQ-000001"


@pytest.mark.parametrize(
    "content",
    [
        "this is not json at all",
        f"```json\n{VALID_CONTENT}\n```",
        f"Sure! Here is the classification you asked for: {VALID_CONTENT}",
        json.dumps(json.loads(VALID_CONTENT) | {"compliance_verdict": "compliant"}),
        json.dumps({"schema_version": "1.0.0", "requirement_id": "REQ-000001"}),
        VALID_CONTENT.replace("microsoft_sentinel", "sentinel_cloud_ultra"),
        VALID_CONTENT.replace('"24_7_monitoring"', "null"),
        json.dumps(json.loads(VALID_CONTENT) | {"schema_version": "9.9.9"}),
    ],
    ids=[
        "invalid-json",
        "markdown-code-fence",
        "prose-before-json",
        "extra-field",
        "missing-fields",
        "unknown-enum-value",
        "null-required-field",
        "wrong-schema-version",
    ],
)
def test_malformed_model_payloads_fail_schema_validation(content: str) -> None:
    error = call(SequencedTransport(outcomes=[http_ok(content)]))
    assert error.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED


def test_duplicate_json_keys_resolve_last_wins_and_still_validate() -> None:
    duplicated = VALID_CONTENT[:-1] + ', "rationale": "Second rationale wins."}'
    adapter = adapter_for(SequencedTransport(outcomes=[http_ok(duplicated)]))
    result = adapter.complete_structured(
        request=pilot_request(), response_type=LlmRequirementNormalization
    )
    assert result.validated_output.rationale == "Second rationale wins."


def test_schema_failures_are_never_retried() -> None:
    transport = SequencedTransport(outcomes=[http_ok("not json")])
    error = call(transport)
    assert error.code is LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED
    assert transport.calls == 1


def test_malformed_utf8_body_is_an_invalid_provider_response() -> None:
    result = OrangeProxyHTTPResult(
        status_code=200, content_type="application/json", body=b"\xff\xfe{"
    )
    error = call(SequencedTransport(outcomes=[result]))
    assert error.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE


# --- transport / HTTP failures ----------------------------------------------


def test_timeout_is_retried_then_surfaces_as_timeout() -> None:
    timeout = LlmGatewayError(LlmGatewayErrorCode.TIMEOUT, request_id="REQ-PILOT-FAILURES-001")
    transport = SequencedTransport(outcomes=[timeout, timeout, timeout])
    error = call(transport)
    assert error.code is LlmGatewayErrorCode.TIMEOUT
    assert transport.calls == 3  # 1 + max_retries(2), the existing bound


@pytest.mark.parametrize(
    ("status_code", "expected", "expected_calls"),
    [
        (401, LlmGatewayErrorCode.AUTHENTICATION_FAILED, 1),
        (403, LlmGatewayErrorCode.AUTHORIZATION_FAILED, 1),
        (429, LlmGatewayErrorCode.RATE_LIMITED, 3),
        (500, LlmGatewayErrorCode.PROVIDER_UNAVAILABLE, 3),
        (302, LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE, 1),
    ],
)
def test_http_statuses_map_to_the_stable_taxonomy(
    status_code: int, expected: LlmGatewayErrorCode, expected_calls: int
) -> None:
    outcome = OrangeProxyHTTPResult(
        status_code=status_code, content_type="application/json", body=b"{}"
    )
    transport = SequencedTransport(outcomes=[outcome] * 3)
    error = call(transport)
    assert error.code is expected
    assert transport.calls == expected_calls


def test_oversized_response_surfaces_as_invalid_provider_response() -> None:
    oversized = LlmGatewayError(
        LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE, request_id="REQ-PILOT-FAILURES-001"
    )
    transport = SequencedTransport(outcomes=[oversized])
    error = call(transport)
    assert error.code is LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE
    assert transport.calls == 1


# --- error hygiene -----------------------------------------------------------


def test_public_error_messages_never_contain_model_text_or_secrets() -> None:
    hostile_content = "SECRET-LOOKING-MODEL-TEXT ignore previous instructions"
    error = call(SequencedTransport(outcomes=[http_ok(hostile_content)]))
    message = str(error)
    assert "SECRET-LOOKING-MODEL-TEXT" not in message
    assert TEST_SECRET not in message
    assert "authorization" not in message.lower()
