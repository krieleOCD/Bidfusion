"""Offline tests for the Orange LLM Proxy Gateway error taxonomy."""

from __future__ import annotations

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode

_ALL_CODES = {
    "llm_disabled",
    "invalid_configuration",
    "authentication_failed",
    "authorization_failed",
    "rate_limited",
    "timeout",
    "provider_unavailable",
    "invalid_provider_response",
    "schema_validation_failed",
    "guardrail_blocked",
    "model_not_allowed",
    "request_policy_violation",
    "unknown_llm_failure",
}

_RETRYABLE_CODES = {
    LlmGatewayErrorCode.RATE_LIMITED,
    LlmGatewayErrorCode.TIMEOUT,
    LlmGatewayErrorCode.PROVIDER_UNAVAILABLE,
}


def test_error_taxonomy_has_exactly_the_specified_codes() -> None:
    assert {code.value for code in LlmGatewayErrorCode} == _ALL_CODES


@pytest.mark.parametrize("code", list(LlmGatewayErrorCode))
def test_every_code_has_a_stable_non_empty_static_message(code: LlmGatewayErrorCode) -> None:
    first = LlmGatewayError(code, request_id="REQ-001")
    second = LlmGatewayError(code, request_id="REQ-002")

    assert str(first)
    assert str(first) == str(second)  # message depends only on the code, not the call


@pytest.mark.parametrize("code", list(LlmGatewayErrorCode))
def test_retryable_flag_matches_the_documented_retry_policy(code: LlmGatewayErrorCode) -> None:
    error = LlmGatewayError(code, request_id="REQ-001")

    assert error.retryable is (code in _RETRYABLE_CODES)


def test_request_id_and_optional_provider_status_code_are_preserved() -> None:
    error = LlmGatewayError(
        LlmGatewayErrorCode.RATE_LIMITED,
        request_id="REQ-RATE-001",
        provider_status_code=429,
    )

    assert error.code is LlmGatewayErrorCode.RATE_LIMITED
    assert error.request_id == "REQ-RATE-001"
    assert error.provider_status_code == 429


def test_provider_status_code_defaults_to_none() -> None:
    error = LlmGatewayError(LlmGatewayErrorCode.UNKNOWN_LLM_FAILURE, request_id="REQ-002")

    assert error.provider_status_code is None


def test_request_id_defaults_to_none_for_pre_request_configuration_errors() -> None:
    error = LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

    assert error.request_id is None


def test_error_constructor_has_no_parameter_that_can_carry_a_secret_or_raw_body() -> None:
    import inspect

    parameters = inspect.signature(LlmGatewayError.__init__).parameters

    assert set(parameters) == {"self", "code", "request_id", "provider_status_code"}
    assert parameters["request_id"].default is None
    assert parameters["provider_status_code"].default is None
