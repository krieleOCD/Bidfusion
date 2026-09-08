"""Gateway registration tests for the ``rfp_requirement_normalization`` operation.

The operation is registered exactly like the synthetic smoke operation:
a closed :class:`StructuredLlmOperation` member, a matching
:class:`ModelPolicyKey`, an entry in the model policy, and an
operation-scoped data-classification policy. Everything runs offline
through injected fake transports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter, OrangeProxyHTTPResult
from bidfusion.llm_gateway.policy import (
    ALLOWED_MODELS,
    OPERATION_DATA_CLASSIFICATIONS,
    allowed_data_classifications,
    resolve_model,
)
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
    SyntheticGatewayResult,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import OrangeProxySettings, load_orange_proxy_settings
from bidfusion.schemas.common import DataClassification

TEST_SECRET = "offline-test-orange-key"


def enabled_settings() -> OrangeProxySettings:
    return load_orange_proxy_settings(
        {"BIDFUSION_LLM_ENABLED": "true", "BIDFUSION_LLM_API_KEY": TEST_SECRET}
    )


def secret_resolver() -> EnvironmentSecretResolver:
    return EnvironmentSecretResolver({"BIDFUSION_LLM_API_KEY": TEST_SECRET})


@dataclass
class SingleResultTransport:
    """Fake transport returning one canned success result."""

    result: OrangeProxyHTTPResult
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
        return self.result


class ExplodingTransport:
    """Transport that must never be reached."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        request_id: str,
    ) -> OrangeProxyHTTPResult:
        raise AssertionError("the transport must not be called")


def synthetic_success() -> OrangeProxyHTTPResult:
    body = json.dumps(
        {
            "model": "openai/gpt-5.4-mini",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"title":"ok","items":[],"confidence":1.0}',
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode()
    return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


def normalization_request(
    *,
    data_classification: DataClassification = DataClassification.ANONYMIZED_INTERNAL_PILOT,
    model_policy_key: ModelPolicyKey = ModelPolicyKey.RFP_REQUIREMENT_NORMALIZATION,
) -> StructuredLlmRequest:
    return StructuredLlmRequest(
        operation=StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION,
        messages=(LlmMessage(role=LlmMessageRole.USER, content="One synthetic requirement."),),
        response_schema_name="llm_requirement_normalization",
        request_id="REQ-PILOT-GATEWAY-001",
        data_classification=data_classification,
        model_policy_key=model_policy_key,
        guardrail_policy_key=GuardrailPolicyKey.DEFAULT,
    )


def adapter_for(transport: SingleResultTransport | ExplodingTransport) -> OrangeProxyAdapter:
    class ZeroClock:
        def monotonic_ms(self) -> int:
            return 0

    class NoSleep:
        def sleep(self, seconds: float) -> None:  # noqa: ARG002 - protocol signature
            return None

    return OrangeProxyAdapter(
        settings=enabled_settings(),
        secret_resolver=secret_resolver(),
        transport=transport,
        clock=ZeroClock(),
        sleeper=NoSleep(),
    )


# --- operation registration --------------------------------------------------


def test_operation_member_exists_with_stable_wire_value() -> None:
    assert StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION.value == (
        "rfp_requirement_normalization"
    )


def test_model_policy_key_resolves_to_an_allowed_model() -> None:
    model = resolve_model(ModelPolicyKey.RFP_REQUIREMENT_NORMALIZATION)
    assert model in ALLOWED_MODELS


def test_every_operation_has_a_data_classification_policy() -> None:
    assert set(OPERATION_DATA_CLASSIFICATIONS) == set(StructuredLlmOperation)


def test_pilot_operation_allows_only_the_anonymized_pilot_classification() -> None:
    allowed = allowed_data_classifications(StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION)
    assert allowed == frozenset({DataClassification.ANONYMIZED_INTERNAL_PILOT})


def test_synthetic_smoke_operation_stays_public_only() -> None:
    allowed = allowed_data_classifications(StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE)
    assert allowed == frozenset({DataClassification.PUBLIC})


def test_anonymized_pilot_classification_exists() -> None:
    assert DataClassification.ANONYMIZED_INTERNAL_PILOT.value == "ANONYMIZED_INTERNAL_PILOT"


# --- adapter routing ---------------------------------------------------------


def test_adapter_routes_the_pilot_operation_to_the_orange_proxy() -> None:
    transport = SingleResultTransport(result=synthetic_success())
    adapter = adapter_for(transport)

    result = adapter.complete_structured(
        request=normalization_request(), response_type=SyntheticGatewayResult
    )

    assert transport.calls == 1
    assert result.operation is StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION
    assert result.model_requested in ALLOWED_MODELS


def test_mismatched_model_policy_key_is_a_policy_violation() -> None:
    adapter = adapter_for(ExplodingTransport())

    with pytest.raises(LlmGatewayError) as failure:
        adapter.complete_structured(
            request=normalization_request(
                model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE
            ),
            response_type=SyntheticGatewayResult,
        )
    assert failure.value.code is LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION


@pytest.mark.parametrize(
    "classification",
    [
        DataClassification.PUBLIC,
        DataClassification.INTERNAL,
        DataClassification.CONFIDENTIAL,
        DataClassification.RESTRICTED,
    ],
)
def test_pilot_operation_rejects_every_other_classification_before_transport(
    classification: DataClassification,
) -> None:
    adapter = adapter_for(ExplodingTransport())

    with pytest.raises(LlmGatewayError) as failure:
        adapter.complete_structured(
            request=normalization_request(data_classification=classification),
            response_type=SyntheticGatewayResult,
        )
    assert failure.value.code is LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION


def test_synthetic_operation_rejects_the_pilot_classification() -> None:
    adapter = adapter_for(ExplodingTransport())
    smoke_request = StructuredLlmRequest(
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        messages=(LlmMessage(role=LlmMessageRole.USER, content="Return a synthetic object."),),
        response_schema_name="synthetic_gateway_result",
        request_id="REQ-PILOT-GATEWAY-002",
        data_classification=DataClassification.ANONYMIZED_INTERNAL_PILOT,
        model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
    )

    with pytest.raises(LlmGatewayError) as failure:
        adapter.complete_structured(request=smoke_request, response_type=SyntheticGatewayResult)
    assert failure.value.code is LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION


def test_disabled_gateway_never_reaches_the_transport_for_the_pilot_operation() -> None:
    adapter = OrangeProxyAdapter(
        settings=load_orange_proxy_settings({"BIDFUSION_LLM_ENABLED": "false"}),
        secret_resolver=secret_resolver(),
        transport=ExplodingTransport(),
    )

    with pytest.raises(LlmGatewayError) as failure:
        adapter.complete_structured(
            request=normalization_request(), response_type=SyntheticGatewayResult
        )
    assert failure.value.code is LlmGatewayErrorCode.LLM_DISABLED
