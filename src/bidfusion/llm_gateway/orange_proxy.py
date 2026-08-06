"""Orange LLM Proxy HTTP transport and adapter (ADR-0013).

This is the only module allowed to know about Orange-specific wire
details: the ``/chat/completions`` OpenAI-compatible request/response
shape, bearer-token auth, and (best-effort, unverified) guardrail-block
response conventions. ``port.py`` must stay ignorant of all of this.

Guardrail-block detection note: the exact Orange Proxy error response
shape for a blocked guardrail is not conclusively documented at the time
of writing. Detection here is deliberately narrow — a strict structural
match on a synthetic, documented convention — rather than free-text
scanning of error messages. If the real proxy uses a different shape,
this detection will simply miss it and fall through to the generic
``INVALID_PROVIDER_RESPONSE`` mapping (fail-closed, never silently
"succeeds"); this is a known limitation to revisit once real Orange Proxy
error-response documentation is available.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from http.client import HTTPResponse
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.policy import ALLOWED_MODELS, resolve_guardrails, resolve_model
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    GuardrailStatus,
    LlmCallStatus,
    ModelPolicyKey,
    SchemaValidationStatus,
    StructuredLlmOperation,
    StructuredLlmRequest,
    StructuredLlmResult,
    StructuredLlmUsage,
    T,
)
from bidfusion.llm_gateway.secrets import SecretResolver
from bidfusion.llm_gateway.settings import OrangeProxySettings
from bidfusion.ports import ExternalCapabilityError
from bidfusion.schemas.llm import LLMFinishReason

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_EXPECTED_CONTENT_TYPE = "application/json"
_GUARDRAIL_BLOCK_STATUS = 400
_BACKOFF_BASE_SECONDS: float = 0.5
_MAX_BACKOFF_SECONDS: float = 4.0

#: Only one (operation, model_policy_key) pair exists in this slice. Every
#: future operation must add its expected key here before it can be routed
#: — an unmapped or mismatched pair is a REQUEST_POLICY_VIOLATION.
_OPERATION_MODEL_POLICY_KEY: dict[StructuredLlmOperation, ModelPolicyKey] = {
    StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE: ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
}

_RETRYABLE_STATUS_CODES: dict[int, LlmGatewayErrorCode] = {
    429: LlmGatewayErrorCode.RATE_LIMITED,
    500: LlmGatewayErrorCode.PROVIDER_UNAVAILABLE,
    502: LlmGatewayErrorCode.PROVIDER_UNAVAILABLE,
    503: LlmGatewayErrorCode.PROVIDER_UNAVAILABLE,
    408: LlmGatewayErrorCode.TIMEOUT,
    504: LlmGatewayErrorCode.TIMEOUT,
}
_NON_RETRYABLE_STATUS_CODES: dict[int, LlmGatewayErrorCode] = {
    401: LlmGatewayErrorCode.AUTHENTICATION_FAILED,
    403: LlmGatewayErrorCode.AUTHORIZATION_FAILED,
}


def _error_for_status(status_code: int) -> tuple[LlmGatewayErrorCode, bool]:
    if status_code in _RETRYABLE_STATUS_CODES:
        return _RETRYABLE_STATUS_CODES[status_code], True
    if status_code in _NON_RETRYABLE_STATUS_CODES:
        return _NON_RETRYABLE_STATUS_CODES[status_code], False
    return LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE, False


def _backoff_seconds(attempt: int) -> float:
    delay: float = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return min(delay, _MAX_BACKOFF_SECONDS)


_MAX_API_KEY_LENGTH = 512


def _resolved_api_key_is_safe(value: str) -> bool:
    """Conservative bearer-token-safe character check on a resolved secret.

    Applied to the *resolved* key, immediately after secret resolution and
    before any header is built. Only printable ASCII, no embedded
    whitespace, bounded length. Rejects CR/LF, tabs, other ASCII control
    characters, DEL, and non-ASCII — several of which make the standard
    library raise a raw ``ValueError`` when building the HTTP request, and
    that ``ValueError`` message can itself contain the header value (and
    therefore the secret).
    """
    if not value or len(value) > _MAX_API_KEY_LENGTH:
        return False
    if any(character.isspace() for character in value):
        return False
    return all(0x20 <= ord(character) <= 0x7E for character in value)


def _classify_header_failure(failure: ValueError) -> LlmGatewayErrorCode:
    """Classify a header-construction/send failure without re-exposing its text.

    ``str(failure)`` is inspected only in-process to pick a stable code; it
    is never included in the ``LlmGatewayError`` raised from this.
    """
    if "authorization" in str(failure).lower():
        return LlmGatewayErrorCode.AUTHENTICATION_FAILED
    return LlmGatewayErrorCode.INVALID_CONFIGURATION


@dataclass(frozen=True, slots=True)
class OrangeProxyHTTPResult:
    """Minimal HTTP result whose representation never contains response content."""

    status_code: int
    content_type: str | None
    body: bytes = field(repr=False)


class OrangeProxyTransport(Protocol):
    """Injectable HTTP seam used to keep automated tests offline."""

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        request_id: str,
    ) -> OrangeProxyHTTPResult:
        """Send one ``/chat/completions`` request."""
        ...


class OrangeNoRedirectHandler(HTTPRedirectHandler):
    """Rejects every redirect. The Orange Proxy is not expected to redirect.

    Declining unconditionally (rather than allow-listing same-host
    redirects) means no follow-up request is ever constructed, so the
    ``Authorization`` header can never be forwarded to a different host —
    the simplest policy that is trivially correct by construction.
    """

    def redirect_request(  # noqa: D102 - stdlib signature, no useful docstring to add
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> Request | None:
        return None


class Clock(Protocol):
    """Injectable time source so tests never depend on real elapsed time."""

    def monotonic_ms(self) -> int: ...


class Sleeper(Protocol):
    """Injectable backoff delay so tests never really wait."""

    def sleep(self, seconds: float) -> None: ...


class _RealClock:
    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)


class _RealSleeper:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class UrllibOrangeProxyTransport:
    """Standard-library transport: bounded reads, no redirects, TLS untouched."""

    def __init__(self) -> None:
        self.opener: OpenerDirector = build_opener(OrangeNoRedirectHandler())

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        request_id: str,
    ) -> OrangeProxyHTTPResult:
        try:
            http_request = Request(url=url, data=body, headers=headers, method="POST")
            with self.opener.open(http_request, timeout=timeout_seconds) as response:
                return OrangeProxyHTTPResult(
                    status_code=response.status,
                    content_type=response.headers.get("Content-Type"),
                    body=self._read_bounded(response, request_id),
                )
        except HTTPError as failure:
            content_type = failure.headers.get("Content-Type") if failure.headers else None
            error_body = self._read_bounded(failure, request_id)
            failure.close()
            return OrangeProxyHTTPResult(
                status_code=failure.code, content_type=content_type, body=error_body
            )
        except TimeoutError:
            raise LlmGatewayError(LlmGatewayErrorCode.TIMEOUT, request_id=request_id) from None
        except URLError as failure:
            if isinstance(failure.reason, TimeoutError):
                raise LlmGatewayError(LlmGatewayErrorCode.TIMEOUT, request_id=request_id) from None
            raise LlmGatewayError(
                LlmGatewayErrorCode.PROVIDER_UNAVAILABLE, request_id=request_id
            ) from None
        except ValueError as failure:
            # Header construction/send failures (including
            # UnicodeEncodeError, a ValueError subclass) can echo the raw
            # header value — and therefore the secret — in their message.
            # Never let that text escape; classify and discard it here.
            code = _classify_header_failure(failure)
            raise LlmGatewayError(code, request_id=request_id) from None
        except OSError:
            raise LlmGatewayError(
                LlmGatewayErrorCode.PROVIDER_UNAVAILABLE, request_id=request_id
            ) from None

    @staticmethod
    def _read_bounded(response: HTTPResponse | HTTPError, request_id: str) -> bytes:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise LlmGatewayError(
                LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE, request_id=request_id
            )
        return body


class _OrangeChoiceMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    content: str


class _OrangeChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    message: _OrangeChoiceMessage
    finish_reason: str


class _OrangeUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class _OrangeChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    model: str | None = None
    choices: list[_OrangeChoice] = Field(min_length=1)
    usage: _OrangeUsage | None = None


class _OrangeGuardrailErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    type: Literal["guardrail_blocked"]


class _OrangeGuardrailErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    error: _OrangeGuardrailErrorDetail


def _is_guardrail_blocked(status_code: int, body: bytes) -> bool:
    if status_code != _GUARDRAIL_BLOCK_STATUS:
        return False
    try:
        _OrangeGuardrailErrorBody.model_validate_json(body)
    except ValidationError:
        return False
    return True


def _map_finish_reason(raw: str, request_id: str) -> LLMFinishReason:
    if raw == "stop":
        return LLMFinishReason.COMPLETED
    if raw == "length":
        return LLMFinishReason.LENGTH
    raise LlmGatewayError(LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE, request_id=request_id)


class OrangeProxyAdapter:
    """Translate BidFusion structured LLM requests to the Orange Proxy."""

    def __init__(
        self,
        settings: OrangeProxySettings,
        secret_resolver: SecretResolver,
        transport: OrangeProxyTransport | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._settings = settings
        self._secret_resolver = secret_resolver
        self._transport = UrllibOrangeProxyTransport() if transport is None else transport
        self._clock = _RealClock() if clock is None else clock
        self._sleeper = _RealSleeper() if sleeper is None else sleeper

    def __repr__(self) -> str:
        """Expose only non-secret route metadata in diagnostics."""
        return (
            f"{type(self).__name__}(provider={self._settings.provider!r}, "
            f"model={self._settings.default_model!r})"
        )

    def complete_structured(
        self,
        *,
        request: StructuredLlmRequest,
        response_type: type[T],
    ) -> StructuredLlmResult[T]:
        """Return a normalized, schema-validated result or raise ``LlmGatewayError``."""
        if not self._settings.enabled:
            raise LlmGatewayError(LlmGatewayErrorCode.LLM_DISABLED, request_id=request.request_id)

        expected_key = _OPERATION_MODEL_POLICY_KEY.get(request.operation)
        if expected_key is None or request.model_policy_key != expected_key:
            raise LlmGatewayError(
                LlmGatewayErrorCode.REQUEST_POLICY_VIOLATION, request_id=request.request_id
            )

        resolved_model = resolve_model(request.model_policy_key)
        if resolved_model != self._settings.default_model or resolved_model not in ALLOWED_MODELS:
            raise LlmGatewayError(
                LlmGatewayErrorCode.MODEL_NOT_ALLOWED, request_id=request.request_id
            )

        secret_ref = self._settings.provider_config.secret_ref
        if secret_ref is None:
            raise LlmGatewayError(
                LlmGatewayErrorCode.AUTHENTICATION_FAILED, request_id=request.request_id
            )
        try:
            api_key = self._secret_resolver.resolve(secret_ref)
        except ExternalCapabilityError:
            raise LlmGatewayError(
                LlmGatewayErrorCode.AUTHENTICATION_FAILED, request_id=request.request_id
            ) from None

        if not _resolved_api_key_is_safe(api_key):
            # Reject before any header or transport call is built; never
            # include the key itself in the error.
            raise LlmGatewayError(
                LlmGatewayErrorCode.AUTHENTICATION_FAILED, request_id=request.request_id
            )

        payload = self._request_payload(request, resolved_model, response_type)
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "user-agent": "bidfusion/0.1",
        }
        url = str(self._settings.provider_config.endpoint)
        timeout_seconds = self._settings.provider_config.timeout_seconds
        max_attempts = 1 + self._settings.max_retries
        start_ms = self._clock.monotonic_ms()

        for attempt in range(1, max_attempts + 1):
            try:
                result = self._transport.post(
                    url=url,
                    headers=headers,
                    body=body,
                    timeout_seconds=timeout_seconds,
                    request_id=request.request_id,
                )
            except LlmGatewayError as failure:
                if failure.retryable and attempt < max_attempts:
                    self._sleeper.sleep(_backoff_seconds(attempt))
                    continue
                raise
            except ValueError as failure:
                # Defense in depth: any transport implementation (the real
                # one or an injected one) that leaks a raw header
                # construction/encoding failure is normalized here too —
                # never retried, and the raw message (which can contain the
                # Authorization header) is never re-exposed.
                code = _classify_header_failure(failure)
                raise LlmGatewayError(code, request_id=request.request_id) from None

            if result.status_code == 200:
                parsed = self._parse_success(request, result)
                duration_ms = self._clock.monotonic_ms() - start_ms
                return self._build_result(
                    request, parsed, response_type, attempt, duration_ms, resolved_model
                )

            if _is_guardrail_blocked(result.status_code, result.body):
                raise LlmGatewayError(
                    LlmGatewayErrorCode.GUARDRAIL_BLOCKED,
                    request_id=request.request_id,
                    provider_status_code=result.status_code,
                )

            code, retryable = _error_for_status(result.status_code)
            if retryable and attempt < max_attempts:
                self._sleeper.sleep(_backoff_seconds(attempt))
                continue
            raise LlmGatewayError(
                code, request_id=request.request_id, provider_status_code=result.status_code
            )

        # Unreachable: every loop iteration either returns or raises.
        raise LlmGatewayError(
            LlmGatewayErrorCode.UNKNOWN_LLM_FAILURE, request_id=request.request_id
        )

    def _request_payload(
        self,
        request: StructuredLlmRequest,
        resolved_model: str,
        response_type: type[T],
    ) -> dict[str, object]:
        schema_instruction = {
            "role": "system",
            "content": (
                "Respond with a single JSON object only - no markdown, no prose, "
                "no code fences - that strictly matches this JSON Schema: "
                + json.dumps(response_type.model_json_schema(), separators=(",", ":"))
            ),
        }
        messages = [schema_instruction] + [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ]
        payload: dict[str, object] = {"model": resolved_model, "messages": messages}

        guardrails = resolve_guardrails(request.guardrail_policy_key)
        if guardrails:
            payload["guardrails"] = [
                {"name": spec.name, "threshold": spec.threshold} for spec in guardrails
            ]
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        return payload

    @staticmethod
    def _parse_success(
        request: StructuredLlmRequest, result: OrangeProxyHTTPResult
    ) -> _OrangeChatCompletionResponse:
        content_type = (result.content_type or "").split(";")[0].strip().lower()
        if content_type != _EXPECTED_CONTENT_TYPE:
            raise LlmGatewayError(
                LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE,
                request_id=request.request_id,
                provider_status_code=result.status_code,
            )
        try:
            return _OrangeChatCompletionResponse.model_validate_json(result.body)
        except ValidationError:
            raise LlmGatewayError(
                LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE,
                request_id=request.request_id,
                provider_status_code=result.status_code,
            ) from None

    def _build_result(
        self,
        request: StructuredLlmRequest,
        parsed: _OrangeChatCompletionResponse,
        response_type: type[T],
        attempt: int,
        duration_ms: int,
        resolved_model: str,
    ) -> StructuredLlmResult[T]:
        choice = parsed.choices[0]
        finish_reason = _map_finish_reason(choice.finish_reason, request.request_id)

        try:
            validated_output = response_type.model_validate_json(choice.message.content.strip())
        except ValidationError:
            raise LlmGatewayError(
                LlmGatewayErrorCode.SCHEMA_VALIDATION_FAILED, request_id=request.request_id
            ) from None

        usage = None
        if parsed.usage is not None:
            try:
                usage = StructuredLlmUsage(
                    input_tokens=parsed.usage.prompt_tokens,
                    output_tokens=parsed.usage.completion_tokens,
                    total_tokens=parsed.usage.total_tokens,
                )
            except ValidationError:
                # E.g. an internally inconsistent usage block
                # (total_tokens != input + output). Never let a raw
                # pydantic ValidationError — which can echo the provider's
                # usage values — escape this adapter.
                raise LlmGatewayError(
                    LlmGatewayErrorCode.INVALID_PROVIDER_RESPONSE,
                    request_id=request.request_id,
                ) from None
        guardrail_status = (
            GuardrailStatus.NOT_APPLIED
            if request.guardrail_policy_key is GuardrailPolicyKey.DEFAULT
            else GuardrailStatus.PASSED
        )
        return StructuredLlmResult(
            request_id=request.request_id,
            operation=request.operation,
            model_requested=resolved_model,
            model_reported=parsed.model,
            status=LlmCallStatus.COMPLETED,
            validated_output=validated_output,
            finish_reason=finish_reason,
            usage=usage,
            duration_ms=duration_ms,
            attempts=attempt,
            guardrail_status=guardrail_status,
            schema_validation_status=SchemaValidationStatus.VALID,
        )
