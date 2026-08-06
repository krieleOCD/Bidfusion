"""Model-agnostic LLM boundary and infrastructure adapters.

Agents declare required capabilities, data policy and cost profile. Provider
translation remains inside this package and never enters business agents.

Two ports currently coexist here (ADR-0013):

- ``LLMPort``/``LLMRequest``/``LLMResponse`` (:mod:`bidfusion.ports`,
  :mod:`bidfusion.schemas.llm`) — the original general-purpose port, kept
  for backward compatibility with its existing consumer, the temporary
  direct Anthropic adapter below.
- ``LlmClient`` (:mod:`bidfusion.llm_gateway.port`) — the new, narrower,
  schema-validated structured port and the intended foundation for future
  business integration, backed by the Orange LLM Proxy Gateway adapter
  (:mod:`bidfusion.llm_gateway.orange_proxy`). New fach code should target
  this port, not the temporary Anthropic adapter.
"""

from bidfusion.llm_gateway.anthropic import (
    AnthropicAdapterSettings,
    AnthropicLLMAdapter,
)
from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.fake import FakeLlmClient
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    LlmClient,
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
    StructuredLlmResult,
    SyntheticGatewayResult,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver, SecretResolver
from bidfusion.llm_gateway.settings import OrangeProxySettings, load_orange_proxy_settings

__all__ = [
    "AnthropicAdapterSettings",
    "AnthropicLLMAdapter",
    "EnvironmentSecretResolver",
    "FakeLlmClient",
    "GuardrailPolicyKey",
    "LlmClient",
    "LlmGatewayError",
    "LlmGatewayErrorCode",
    "LlmMessage",
    "LlmMessageRole",
    "ModelPolicyKey",
    "OrangeProxyAdapter",
    "OrangeProxySettings",
    "SecretResolver",
    "StructuredLlmOperation",
    "StructuredLlmRequest",
    "StructuredLlmResult",
    "SyntheticGatewayResult",
    "load_orange_proxy_settings",
]
