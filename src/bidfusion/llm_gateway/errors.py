"""Stable, provider-neutral error taxonomy for the Orange LLM Proxy Gateway.

Distinct from ``bidfusion.schemas.external.ExternalErrorCode`` (used by the
temporary Anthropic adapter): the structured gateway needs a wider, more
specific taxonomy than the small shared external-capability codes, and
extending the shared enum would ripple into the unrelated Anthropic adapter
and its tests.
"""

from __future__ import annotations

from enum import StrEnum


class LlmGatewayErrorCode(StrEnum):
    """Stable failure codes crossing the ``LlmClient`` port boundary."""

    LLM_DISABLED = "llm_disabled"
    INVALID_CONFIGURATION = "invalid_configuration"
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_FAILED = "authorization_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    MODEL_NOT_ALLOWED = "model_not_allowed"
    REQUEST_POLICY_VIOLATION = "request_policy_violation"
    UNKNOWN_LLM_FAILURE = "unknown_llm_failure"


_RETRYABLE_CODES = frozenset(
    {
        LlmGatewayErrorCode.RATE_LIMITED,
        LlmGatewayErrorCode.TIMEOUT,
        LlmGatewayErrorCode.PROVIDER_UNAVAILABLE,
    }
)

_STATIC_MESSAGES: dict[LlmGatewayErrorCode, str] = {
    LlmGatewayErrorCode.LLM_DISABLED: "the Orange LLM Proxy Gateway is disabled",
    LlmGatewayErrorCode.INVALID_CONFIGURATION: (
        "the Orange LLM Proxy Gateway configuration is invalid"
    ),
    LlmGatewayErrorCode.AUTHENTICATION_FAILED: "authentication with the LLM provider failed",
    LlmGatewayErrorCode.AUTHORIZATION_FAILED: "authorization with the LLM provider failed",
    LlmGatewayErrorCode.RATE_LIMITED: "the LLM provider rate-limited the request",
    LlmGatewayErrorCode.TIMEOUT: "the LLM provider request timed out",
    LlmGatewayErrorCode.PROVIDER_UNAVAILABLE: "the LLM provider is unavailable",
    LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE: "the LLM provider returned an invalid response",
    LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED: "the LLM response failed schema validation",
    LlmGatewayErrorCode.GUARDRAIL_BLOCKED: "a guardrail blocked the request or response",
    LlmGatewayErrorCode.MODEL_NOT_ALLOWED: "the resolved model is not on the allowed model policy",
    LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION: "the request violates the gateway request policy",
    LlmGatewayErrorCode.UNKNOWN_LLM_FAILURE: "an unexpected LLM gateway failure occurred",
}


class LlmGatewayError(RuntimeError):
    """Normalized LlmClient failure: a stable code, never a secret or raw body."""

    def __init__(
        self,
        code: LlmGatewayErrorCode,
        *,
        request_id: str | None = None,
        provider_status_code: int | None = None,
    ) -> None:
        self.code = code
        self.request_id = request_id
        self.provider_status_code = provider_status_code
        self.retryable = code in _RETRYABLE_CODES
        super().__init__(_STATIC_MESSAGES[code])
