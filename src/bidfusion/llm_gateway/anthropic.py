"""Temporary direct Anthropic adapter behind BidFusion's provider-neutral LLM port."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.client import HTTPResponse
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from bidfusion.llm_gateway.secrets import SecretResolver
from bidfusion.ports import ExternalCapabilityError
from bidfusion.schemas.common import DataClassification
from bidfusion.schemas.external import ExternalErrorCode, ProviderConfig
from bidfusion.schemas.llm import (
    LLMFinishReason,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)

_ANTHROPIC_API_VERSION = "2023-06-01"
_ANTHROPIC_HOST = "api.anthropic.com"
_ANTHROPIC_PATH = "/v1/messages"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class AnthropicAdapterSettings:
    """Non-secret infrastructure settings for the temporary Claude route."""

    provider: ProviderConfig
    model: str
    max_output_tokens: int = 1024
    route_id: str = "direct-test-route"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Anthropic model must not be blank")
        if not 1 <= self.max_output_tokens <= 128_000:
            raise ValueError("Anthropic max_output_tokens must be between 1 and 128000")
        if not self.route_id.strip():
            raise ValueError("Anthropic route_id must not be blank")
        if self.provider.secret_ref is None:
            raise ValueError("Anthropic provider configuration requires a secret reference")

        endpoint = self.provider.endpoint
        if (
            endpoint.scheme != "https"
            or endpoint.host != _ANTHROPIC_HOST
            or endpoint.port not in {None, 443}
            or endpoint.path != _ANTHROPIC_PATH
        ):
            raise ValueError(
                "Anthropic adapter endpoint must be https://api.anthropic.com/v1/messages"
            )


@dataclass(frozen=True, slots=True)
class AnthropicHTTPResult:
    """Minimal HTTP result whose representation never contains response content."""

    status_code: int
    body: bytes = field(repr=False)


class AnthropicTransport(Protocol):
    """Injectable HTTP seam used to keep automated tests offline."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> AnthropicHTTPResult:
        """Send one Messages API request."""
        ...


class UrllibAnthropicTransport:
    """Small standard-library transport with bounded response reads."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> AnthropicHTTPResult:
        request = Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                return AnthropicHTTPResult(
                    status_code=response.status,
                    body=self._read_bounded(response),
                )
        except HTTPError as failure:
            failure.close()
            return AnthropicHTTPResult(status_code=failure.code, body=b"")
        except TimeoutError:
            raise ExternalCapabilityError(ExternalErrorCode.TIMEOUT) from None
        except URLError as failure:
            if isinstance(failure.reason, TimeoutError):
                raise ExternalCapabilityError(ExternalErrorCode.TIMEOUT) from None
            raise ExternalCapabilityError(ExternalErrorCode.UNAVAILABLE) from None
        except OSError:
            raise ExternalCapabilityError(ExternalErrorCode.UNAVAILABLE) from None

    @staticmethod
    def _read_bounded(response: HTTPResponse) -> bytes:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE)
        return body


class _AnthropicContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    type: str
    text: str | None = None


class _AnthropicUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class _AnthropicMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    content: list[_AnthropicContentBlock]
    stop_reason: str
    usage: _AnthropicUsage


class AnthropicLLMAdapter:
    """Translate BidFusion LLM requests to the direct Anthropic Messages API."""

    def __init__(
        self,
        settings: AnthropicAdapterSettings,
        secret_resolver: SecretResolver,
        transport: AnthropicTransport | None = None,
    ) -> None:
        self._settings = settings
        self._secret_resolver = secret_resolver
        self._transport = UrllibAnthropicTransport() if transport is None else transport

    def __repr__(self) -> str:
        """Expose only non-secret route metadata in diagnostics."""
        return (
            f"{type(self).__name__}(model={self._settings.model!r}, "
            f"route_id={self._settings.route_id!r})"
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a normalized response or raise a provider-neutral failure."""
        self._enforce_egress_policy(request)
        secret_ref = self._settings.provider.secret_ref
        if secret_ref is None:  # guarded by settings validation; keeps type narrowing explicit
            raise ExternalCapabilityError(ExternalErrorCode.AUTHENTICATION_FAILED)
        api_key = self._secret_resolver.resolve(secret_ref)

        result = self._transport.post(
            url=str(self._settings.provider.endpoint),
            headers={
                "anthropic-version": _ANTHROPIC_API_VERSION,
                "content-type": "application/json",
                "user-agent": "bidfusion/0.1",
                "x-api-key": api_key,
            },
            body=json.dumps(self._request_payload(request), separators=(",", ":")).encode(),
            timeout_seconds=self._settings.provider.timeout_seconds,
        )
        if result.status_code != 200:
            raise ExternalCapabilityError(self._error_code_for_status(result.status_code))
        return self._normalize_response(request, result.body)

    @staticmethod
    def _enforce_egress_policy(request: LLMRequest) -> None:
        data_policy = request.requirements.data_policy
        if (
            data_policy.classification is not DataClassification.PUBLIC
            or data_policy.local_processing_preferred
            or request.input_artifacts
            or request.requirements.capabilities.vision
        ):
            raise ExternalCapabilityError(ExternalErrorCode.POLICY_BLOCKED)

    def _request_payload(self, request: LLMRequest) -> dict[str, object]:
        if request.prompt is None:
            raise ExternalCapabilityError(ExternalErrorCode.POLICY_BLOCKED)
        payload: dict[str, object] = {
            "max_tokens": self._settings.max_output_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
            "model": self._settings.model,
        }
        if request.output_spec is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": request.output_spec.json_schema,
                }
            }
        return payload

    def _normalize_response(self, request: LLMRequest, body: bytes) -> LLMResponse:
        try:
            message = _AnthropicMessage.model_validate_json(body)
        except ValidationError:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE) from None

        if message.stop_reason == "refusal":
            raise ExternalCapabilityError(ExternalErrorCode.POLICY_BLOCKED)
        if message.stop_reason in {"max_tokens", "model_context_window_exceeded"}:
            finish_reason = LLMFinishReason.LENGTH
        elif message.stop_reason in {"end_turn", "stop_sequence"}:
            finish_reason = LLMFinishReason.COMPLETED
        else:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE)

        text = "".join(
            block.text for block in message.content if block.type == "text" and block.text
        ).strip()
        if not text:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE)

        usage = LLMUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        if request.output_spec is None:
            return LLMResponse(
                request_id=request.request_id,
                output_text=text,
                finish_reason=finish_reason,
                route_id=self._settings.route_id,
                usage=usage,
            )

        try:
            structured_output = _JSON_OBJECT.validate_json(text)
        except ValidationError:
            raise ExternalCapabilityError(ExternalErrorCode.INVALID_RESPONSE) from None
        return LLMResponse(
            request_id=request.request_id,
            structured_output=structured_output,
            finish_reason=finish_reason,
            route_id=self._settings.route_id,
            usage=usage,
        )

    @staticmethod
    def _error_code_for_status(status_code: int) -> ExternalErrorCode:
        if status_code in {401, 403}:
            return ExternalErrorCode.AUTHENTICATION_FAILED
        if status_code in {408, 504}:
            return ExternalErrorCode.TIMEOUT
        if status_code == 429:
            return ExternalErrorCode.RATE_LIMITED
        if status_code in {400, 404, 409, 413, 422}:
            return ExternalErrorCode.INVALID_RESPONSE
        return ExternalErrorCode.UNAVAILABLE
