"""Offline tests for the Orange LLM Proxy model and guardrail policy."""

from __future__ import annotations

import dataclasses

import pytest

from bidfusion.llm_gateway.policy import (
    ALLOWED_MODELS,
    GUARDRAIL_POLICY,
    MODEL_POLICY,
    GuardrailSpec,
    resolve_guardrails,
    resolve_model,
)
from bidfusion.llm_gateway.port import GuardrailPolicyKey, ModelPolicyKey


def test_allowed_models_contains_exactly_the_one_permitted_model() -> None:
    assert ALLOWED_MODELS == frozenset({"openai/gpt-5.4-mini"})


def test_model_policy_covers_every_model_policy_key() -> None:
    assert set(MODEL_POLICY) == set(ModelPolicyKey)


def test_resolve_model_maps_synthetic_smoke_to_the_allowed_model() -> None:
    model = resolve_model(ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE)

    assert model == "openai/gpt-5.4-mini"
    assert model in ALLOWED_MODELS


def test_guardrail_policy_covers_every_guardrail_policy_key() -> None:
    assert set(GUARDRAIL_POLICY) == set(GuardrailPolicyKey)


def test_default_guardrail_policy_requests_no_guardrails() -> None:
    assert resolve_guardrails(GuardrailPolicyKey.DEFAULT) == ()


def test_synthetic_prompt_injection_probe_resolves_to_one_allowlisted_guardrail() -> None:
    guardrails = resolve_guardrails(GuardrailPolicyKey.SYNTHETIC_PROMPT_INJECTION_PROBE)

    assert guardrails == (GuardrailSpec(name="speleoguards_llamapromptguard", threshold=0.8),)


def test_guardrail_spec_is_immutable() -> None:
    spec = GuardrailSpec(name="speleoguards_llamapromptguard", threshold=0.8)

    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.threshold = 0.5  # type: ignore[misc]
