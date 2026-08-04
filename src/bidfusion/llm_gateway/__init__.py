"""Model-agnostic LLM boundary and infrastructure adapters.

Agents declare required capabilities, data policy and cost profile. Provider
translation remains inside this package and never enters business agents.
"""

from bidfusion.llm_gateway.anthropic import (
    AnthropicAdapterSettings,
    AnthropicLLMAdapter,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver, SecretResolver

__all__ = [
    "AnthropicAdapterSettings",
    "AnthropicLLMAdapter",
    "EnvironmentSecretResolver",
    "SecretResolver",
]
