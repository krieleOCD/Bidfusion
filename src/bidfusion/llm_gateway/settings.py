"""Fail-closed settings for the Orange LLM Proxy Gateway (ADR-0013).

Only ``BIDFUSION_LLM_*`` environment variables are read here, and only
through an explicit mapping (defaulting to :data:`os.environ`). No
``.env`` file is ever opened or parsed by this module — that stays a
concern of the caller's process environment, never of BidFusion code.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.policy import ALLOWED_MODELS
from bidfusion.schemas.external import ProviderConfig, SecretRef

_PROVIDER_ORANGE_PROXY = "orange_proxy"
_ALLOWED_HOST = "llmproxy.ai.orange"
_ALLOWED_PORTS: frozenset[int | None] = frozenset({None, 443})
_CHAT_COMPLETIONS_PATH = "/chat/completions"
_MAX_TIMEOUT_SECONDS = 120.0
_MIN_RETRIES = 0
_MAX_RETRIES = 2

#: Fixed, non-configurable pointer to the Orange Proxy API key. Distinct
#: from the temporary Anthropic route's ``BIDFUSION_ANTHROPIC_API_KEY``
#: (ADR-0013) — the two must never share a real secret value.
API_KEY_ENV_NAME = "BIDFUSION_LLM_API_KEY"
SECRET_REF = SecretRef(reference=f"secret://env/{API_KEY_ENV_NAME}")

_DEFAULT_BASE_URL = f"https://{_ALLOWED_HOST}"
_DEFAULT_MODEL = "openai/gpt-5.4-mini"
_DEFAULT_TIMEOUT_SECONDS = "60"
_DEFAULT_MAX_RETRIES = "2"
_DEFAULT_ENABLED = "false"


@dataclass(frozen=True, slots=True)
class OrangeProxySettings:
    """Validated, non-secret Orange LLM Proxy configuration."""

    provider: str
    provider_config: ProviderConfig
    default_model: str
    max_retries: int
    enabled: bool

    def __post_init__(self) -> None:
        if self.provider != _PROVIDER_ORANGE_PROXY:
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

        endpoint = self.provider_config.endpoint
        if (
            endpoint.scheme != "https"
            or endpoint.host != _ALLOWED_HOST
            or endpoint.port not in _ALLOWED_PORTS
            or endpoint.path != _CHAT_COMPLETIONS_PATH
        ):
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

        if self.provider_config.timeout_seconds > _MAX_TIMEOUT_SECONDS:
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

        if not (_MIN_RETRIES <= self.max_retries <= _MAX_RETRIES):
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

        if self.default_model not in ALLOWED_MODELS:
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)


def _parse_bool(raw: str) -> bool:
    """Fail-closed boolean parsing.

    Surrounding whitespace and case are ignored (``" True "``, ``"TRUE"``,
    and ``"true"`` all parse as enabled). Any other value — including
    ``"1"``, ``"yes"``, or ``"on"`` — parses as disabled; there is no
    accepted alias list, only case/whitespace-insensitive equality with
    the literal word ``true``.
    """
    return raw.strip().lower() == "true"


def _parse_float(raw: str) -> float:
    try:
        return float(raw.strip())
    except ValueError:
        raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION) from None


def _parse_int(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION) from None


def load_orange_proxy_settings(environ: Mapping[str, str] | None = None) -> OrangeProxySettings:
    """Parse and validate Orange Proxy settings from an explicit environment mapping.

    Every field is validated fail-closed, regardless of ``enabled`` — a
    structurally invalid configuration is rejected even while disabled.
    The API key is required only when ``BIDFUSION_LLM_ENABLED=true``, and
    only its *presence* is checked here; its value is never read into this
    settings object.
    """
    env = os.environ if environ is None else environ

    provider = env.get("BIDFUSION_LLM_PROVIDER", _PROVIDER_ORANGE_PROXY).strip()
    base_url = env.get("BIDFUSION_LLM_BASE_URL", _DEFAULT_BASE_URL).strip().rstrip("/")
    default_model = env.get("BIDFUSION_LLM_DEFAULT_MODEL", _DEFAULT_MODEL).strip()
    enabled = _parse_bool(env.get("BIDFUSION_LLM_ENABLED", _DEFAULT_ENABLED))
    timeout_seconds = _parse_float(
        env.get("BIDFUSION_LLM_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    )
    max_retries = _parse_int(env.get("BIDFUSION_LLM_MAX_RETRIES", _DEFAULT_MAX_RETRIES))

    try:
        provider_config = ProviderConfig.model_validate(
            {
                "endpoint": base_url + _CHAT_COMPLETIONS_PATH,
                "secret_ref": SECRET_REF,
                "timeout_seconds": timeout_seconds,
            }
        )
    except ValidationError:
        raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION) from None

    if enabled:
        api_key = env.get(API_KEY_ENV_NAME)
        if api_key is None or not api_key.strip():
            raise LlmGatewayError(LlmGatewayErrorCode.INVALID_CONFIGURATION)

    return OrangeProxySettings(
        provider=provider,
        provider_config=provider_config,
        default_model=default_model,
        max_retries=max_retries,
        enabled=enabled,
    )
