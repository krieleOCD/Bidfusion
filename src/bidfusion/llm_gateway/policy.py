"""Model and guardrail policy for the Orange LLM Proxy Gateway (ADR-0013).

Only this module, ``settings.py``, and ``orange_proxy.py`` may know concrete
model names or Orange-specific guardrail identifiers. ``port.py`` only knows
the allowlisted policy *keys* (:class:`ModelPolicyKey`,
:class:`GuardrailPolicyKey`); fach code never chooses a model or guardrail
directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from bidfusion.llm_gateway.port import GuardrailPolicyKey, ModelPolicyKey

#: The only model allowed in this slice. Any other configured or resolved
#: value is fail-closed rejected by ``OrangeProxySettings`` and by the
#: adapter's defense-in-depth check against this allowlist.
ALLOWED_MODELS: frozenset[str] = frozenset({"openai/gpt-5.4-mini"})

#: Model-policy-key to concrete model. Every :class:`ModelPolicyKey` member
#: must have an entry here.
#:
#: Documented future keys — NOT implemented, NOT constructible in this
#: slice (no corresponding ``ModelPolicyKey``/``StructuredLlmOperation``
#: member exists yet, so they cannot be executed):
#:   requirement_extraction -> openai/gpt-5.4-mini
#:   complex_review          -> claude-sonnet-4-6@default
MODEL_POLICY: Mapping[ModelPolicyKey, str] = {
    ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE: "openai/gpt-5.4-mini",
}


def resolve_model(key: ModelPolicyKey) -> str:
    """Return the concrete model for an allowlisted model-policy key."""
    return MODEL_POLICY[key]


@dataclass(frozen=True, slots=True)
class GuardrailSpec:
    """One concrete, Orange-side guardrail invocation. Never freely constructed by callers."""

    name: str
    threshold: float


#: Guardrail-policy-key to ordered guardrails to request. An empty tuple
#: means "send no ``guardrails`` field" and rely on the team/key guardrails
#: already configured on the proxy side.
GUARDRAIL_POLICY: Mapping[GuardrailPolicyKey, tuple[GuardrailSpec, ...]] = {
    GuardrailPolicyKey.DEFAULT: (),
    GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE: (
        GuardrailSpec(name="speleoguards_llamapromptguard", threshold=0.8),
    ),
}


def resolve_guardrails(key: GuardrailPolicyKey) -> tuple[GuardrailSpec, ...]:
    """Return the allowlisted guardrail specs for a guardrail-policy key."""
    return GUARDRAIL_POLICY[key]
