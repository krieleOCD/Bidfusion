#!/usr/bin/env python3
"""Run one explicit synthetic connectivity check against the Orange LLM Proxy.

Never part of ``pytest`` and never opens a socket unless invoked directly
with both opt-in flags explicitly set to ``true``:

    BIDFUSION_LLM_ENABLED=true
    BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=true

Sends one short, synthetic, non-confidential prompt and prints only safe,
non-secret metadata (request_id, operation, model, status, token counts if
available, duration, schema-validation outcome). Never prints the prompt,
the response body, the API key, or the Authorization header. Reads no
files, and never touches ``inbox/`` or ``results/``. No ``.env`` file is
read automatically — export the required variables in the environment
before running this script.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from bidfusion.llm_gateway.errors import LlmGatewayError
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter, OrangeProxyTransport
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
from bidfusion.llm_gateway.settings import load_orange_proxy_settings
from bidfusion.schemas.common import DataClassification

_TRUE = "true"


def _smoke_test_authorized(environ: Mapping[str, str]) -> bool:
    """Both explicit opt-in flags must parse as enabled.

    Matching is case- and surrounding-whitespace-insensitive against the
    literal word ``true`` (so ``" True "`` counts); every other value —
    including ``"1"``, ``"yes"``, or ``"on"`` — is treated as disabled.
    """
    return (
        environ.get("BIDFUSION_LLM_ENABLED", "").strip().lower() == _TRUE
        and environ.get("BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS", "").strip().lower() == _TRUE
    )


def _build_request() -> StructuredLlmRequest:
    return StructuredLlmRequest(
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        messages=(
            LlmMessage(
                role=LlmMessageRole.USER,
                content=(
                    "This is a synthetic connectivity check with no customer data. "
                    "Return title 'ok', an empty items list, and confidence 1.0."
                ),
            ),
        ),
        response_schema_name="synthetic_gateway_result",
        request_id="REQ-ORANGE-SYNTHETIC-CONNECTION-CHECK",
        data_classification=DataClassification.PUBLIC,
        model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
        guardrail_policy_key=GuardrailPolicyKey.DEFAULT,
    )


def main(
    environ: Mapping[str, str] | None = None,
    *,
    transport: OrangeProxyTransport | None = None,
) -> int:
    """Run the doubly-gated synthetic smoke check; return a process exit code."""
    env = os.environ if environ is None else environ

    if not _smoke_test_authorized(env):
        print(
            "Orange Proxy smoke test skipped: requires explicit "
            "BIDFUSION_LLM_ENABLED=true and BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=true.",
            file=sys.stderr,
        )
        return 1

    try:
        settings = load_orange_proxy_settings(env)
    except LlmGatewayError as failure:
        print(f"Orange Proxy smoke test failed: {failure.code.value}", file=sys.stderr)
        return 1

    if not settings.enabled:
        print("Orange Proxy smoke test skipped: gateway is disabled.", file=sys.stderr)
        return 1

    adapter = OrangeProxyAdapter(
        settings=settings,
        secret_resolver=EnvironmentSecretResolver(env),
        transport=transport,
    )

    try:
        result = adapter.complete_structured(
            request=_build_request(), response_type=SyntheticGatewayResult
        )
    except LlmGatewayError as failure:
        print(f"Orange Proxy smoke test failed: {failure.code.value}", file=sys.stderr)
        return 1

    usage_summary = (
        "usage unavailable"
        if result.usage is None
        else f"input_tokens={result.usage.input_tokens}, output_tokens={result.usage.output_tokens}"
    )
    print(
        "Orange Proxy smoke test passed: "
        f"request_id={result.request_id}, operation={result.operation.value}, "
        f"model={result.model_requested}, status={result.status.value}, "
        f"{usage_summary}, duration_ms={result.duration_ms}, "
        f"schema_validation={result.schema_validation_status.value}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
