#!/usr/bin/env python3
"""Run one explicit synthetic/public connectivity check against Anthropic."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from bidfusion.llm_gateway import (
    AnthropicAdapterSettings,
    AnthropicLLMAdapter,
    EnvironmentSecretResolver,
)
from bidfusion.ports import ExternalCapabilityError
from bidfusion.schemas import (
    DataClassification,
    LLMRequest,
    ModelCapabilities,
    ModelDataPolicy,
    ModelRequirements,
    ProviderConfig,
    SecretRef,
    StructuredOutputSpec,
)

ROOT = Path(__file__).resolve().parents[1]
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_SECRET_REF = "secret://env/BIDFUSION_LLM_API_KEY"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read inert key/value pairs without expansion or shell evaluation."""
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or _ENV_NAME.fullmatch(name) is None:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _setting(name: str, dotenv: Mapping[str, str], default: str) -> str:
    return os.environ.get(name) or dotenv.get(name) or default


def main() -> int:
    """Send a tiny structured request and report only normalized metadata."""
    dotenv = _read_dotenv(ROOT / ".env")
    secret_ref = SecretRef(
        reference=_setting(
            "BIDFUSION_ANTHROPIC_SECRET_REF",
            dotenv,
            _DEFAULT_SECRET_REF,
        )
    )
    secret_name = EnvironmentSecretResolver.environment_name(secret_ref)
    secret_value = os.environ.get(secret_name) or dotenv.get(secret_name)
    secret_environment = {secret_name: secret_value} if secret_value is not None else {}

    adapter = AnthropicLLMAdapter(
        settings=AnthropicAdapterSettings(
            provider=ProviderConfig.model_validate(
                {
                    "endpoint": _setting(
                        "BIDFUSION_ANTHROPIC_URL",
                        dotenv,
                        "https://api.anthropic.com/v1/messages",
                    ),
                    "secret_ref": secret_ref,
                    "timeout_seconds": 30,
                }
            ),
            model=_setting(
                "BIDFUSION_ANTHROPIC_MODEL",
                dotenv,
                "claude-sonnet-5",
            ),
            max_output_tokens=64,
            route_id="direct-synthetic-check",
        ),
        secret_resolver=EnvironmentSecretResolver(secret_environment),
    )
    request = LLMRequest(
        request_id="REQ-SYNTHETIC-CONNECTION-CHECK",
        prompt=(
            "This is a synthetic connectivity check with no customer data. "
            "Return an object whose status is exactly 'ok'."
        ),
        requirements=ModelRequirements(
            capabilities=ModelCapabilities(structured_output=True),
            data_policy=ModelDataPolicy(
                classification=DataClassification.PUBLIC,
                local_processing_preferred=False,
            ),
        ),
        output_spec=StructuredOutputSpec(
            name="connection_check",
            json_schema={
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["ok"]}},
                "required": ["status"],
                "additionalProperties": False,
            },
        ),
    )

    try:
        response = adapter.generate(request)
    except ExternalCapabilityError as failure:
        print(f"Anthropic connectivity check failed: {failure.code.value}", file=sys.stderr)
        return 1

    if response.structured_output != {"status": "ok"}:
        print("Anthropic connectivity check failed: invalid_response", file=sys.stderr)
        return 1

    usage = response.usage
    usage_summary = (
        "usage unavailable"
        if usage is None
        else f"input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}"
    )
    print(f"Anthropic connectivity check passed (route={response.route_id}, {usage_summary}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
