#!/usr/bin/env python3
"""One explicit synthetic smoke of the ``rfp_requirement_normalization`` operation.

Never part of ``pytest`` and never opens a socket unless invoked directly
with both opt-in flags explicitly set to ``true``:

    BIDFUSION_LLM_ENABLED=true
    BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=true

Sends exactly ONE short SYNTHETIC requirement — never a real RFP, never
customer content — through the Orange Proxy and validates the strict
structured result. Prints only safe metadata (request_id, operation,
model, status, validated enum fields, token counts if available,
duration). Never the prompt, the response body, the API key, or the
Authorization header. Reads no files and no ``.env``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from bidfusion.llm_gateway.errors import LlmGatewayError
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter, OrangeProxyTransport
from bidfusion.llm_gateway.port import (
    GuardrailPolicyKey,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import load_orange_proxy_settings
from bidfusion.rfp_api_pilot.contracts import (
    LlmRequirementNormalization,
    RequirementNormalizationRequest,
)
from bidfusion.rfp_api_pilot.prompt import build_messages
from bidfusion.schemas.common import DataClassification

_TRUE = "true"

SYNTHETIC_REQUIREMENT_ID = "REQ-999901"
SYNTHETIC_REQUIREMENT_TEXT = (
    "The service shall support Microsoft Sentinel monitoring on a 24/7 basis."
)


def _smoke_test_authorized(environ: Mapping[str, str]) -> bool:
    """Both explicit opt-in flags must parse as the literal word ``true``."""
    return (
        environ.get("BIDFUSION_LLM_ENABLED", "").strip().lower() == _TRUE
        and environ.get("BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS", "").strip().lower() == _TRUE
    )


def _build_request() -> StructuredLlmRequest:
    normalization_request = RequirementNormalizationRequest(
        requirement_id=SYNTHETIC_REQUIREMENT_ID,
        requirement_text=SYNTHETIC_REQUIREMENT_TEXT,
    )
    return StructuredLlmRequest(
        operation=StructuredLlmOperation.RFP_REQUIREMENT_NORMALIZATION,
        messages=build_messages(normalization_request),
        response_schema_name="llm_requirement_normalization",
        request_id="REQ-ORANGE-RFP-NORMALIZATION-SYNTHETIC-CHECK",
        data_classification=DataClassification.ANONYMIZED_INTERNAL_PILOT,
        model_policy_key=ModelPolicyKey.RFP_REQUIREMENT_NORMALIZATION,
        guardrail_policy_key=GuardrailPolicyKey.DEFAULT,
        max_output_tokens=1024,
    )


def main(
    environ: Mapping[str, str] | None = None,
    *,
    transport: OrangeProxyTransport | None = None,
) -> int:
    """Run the doubly-gated synthetic normalization smoke; return an exit code."""
    env = os.environ if environ is None else environ

    if not _smoke_test_authorized(env):
        print(
            "RFP normalization smoke test skipped: requires explicit "
            "BIDFUSION_LLM_ENABLED=true and BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS=true.",
            file=sys.stderr,
        )
        return 1

    try:
        settings = load_orange_proxy_settings(env)
    except LlmGatewayError as failure:
        print(f"RFP normalization smoke test failed: {failure.code.value}", file=sys.stderr)
        return 1

    if not settings.enabled:
        print("RFP normalization smoke test skipped: gateway is disabled.", file=sys.stderr)
        return 1

    adapter = OrangeProxyAdapter(
        settings=settings,
        secret_resolver=EnvironmentSecretResolver(env),
        transport=transport,
    )

    try:
        result = adapter.complete_structured(
            request=_build_request(), response_type=LlmRequirementNormalization
        )
    except LlmGatewayError as failure:
        print(f"RFP normalization smoke test failed: {failure.code.value}", file=sys.stderr)
        return 1

    normalization = result.validated_output
    if normalization.requirement_id != SYNTHETIC_REQUIREMENT_ID:
        print("RFP normalization smoke test failed: requirement_id_mismatch", file=sys.stderr)
        return 1

    usage_summary = (
        "usage unavailable"
        if result.usage is None
        else f"input_tokens={result.usage.input_tokens}, output_tokens={result.usage.output_tokens}"
    )
    print(
        "RFP normalization smoke test passed: "
        f"request_id={result.request_id}, operation={result.operation.value}, "
        f"model={result.model_requested}, status={result.status.value}, "
        f"requirement_type={normalization.requirement_type.value}, "
        f"mandatory_status={normalization.mandatory_status.value}, "
        f"technology={normalization.technology.value}, "
        f"capability={normalization.capability.value}, "
        f"normalization_status={normalization.normalization_status.value}, "
        f"confidence_band={normalization.confidence_band.value}, "
        f"{usage_summary}, duration_ms={result.duration_ms}, "
        f"schema_validation={result.schema_validation_status.value}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
