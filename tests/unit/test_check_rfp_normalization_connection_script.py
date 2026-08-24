"""Offline tests for the pilot normalization connectivity script.

The script is never part of pytest network traffic: both opt-in flags
must be exactly ``true`` before the transport is ever reachable, the
content is one short SYNTHETIC requirement (never a real RFP), and the
output is safe metadata only — no prompt, no raw body, no secret, no
authorization header.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from bidfusion.llm_gateway.orange_proxy import OrangeProxyHTTPResult

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_rfp_normalization_connection.py"
)

TEST_SECRET = "offline-test-orange-key"

AUTHORIZED_ENV = {
    "BIDFUSION_LLM_ENABLED": "true",
    "BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": "true",
    "BIDFUSION_LLM_API_KEY": TEST_SECRET,
}


def _load_script() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bidfusion_check_rfp_normalization_connection_script", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


class ExplodingTransport:
    """Fails loudly if gating ever reaches the transport."""

    def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
        raise AssertionError("the pilot smoke script must not reach the transport here")


class FakeSuccessTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs: object) -> OrangeProxyHTTPResult:
        self.calls.append(kwargs)
        content = json.dumps(
            {
                "schema_version": "1.0.0",
                "requirement_id": script.SYNTHETIC_REQUIREMENT_ID,
                "requirement_type": "obligation",
                "mandatory_status": "mandatory",
                "technology": "microsoft_sentinel",
                "capability": "24_7_monitoring",
                "constraints": ["24/7 basis"],
                "conditions": [],
                "exclusions": [],
                "normalization_status": "normalized",
                "confidence_band": "HIGH",
                "ambiguity_flags": [],
                "rationale": "Synthetic Sentinel monitoring obligation.",
            }
        )
        body = json.dumps(
            {
                "model": "openai/gpt-5.4-mini",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16},
            }
        ).encode()
        return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"BIDFUSION_LLM_ENABLED": "true", "BIDFUSION_LLM_API_KEY": TEST_SECRET},
        {"BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": "true"},
        {"BIDFUSION_LLM_ENABLED": "1", "BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": "1"},
    ],
    ids=["nothing-set", "only-enabled", "only-external-tests", "alias-values"],
)
def test_both_explicit_flags_are_required(environ: dict[str, str], capsys: object) -> None:
    exit_code = script.main(environ, transport=ExplodingTransport())
    assert exit_code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "skipped" in captured.err


def test_synthetic_input_only_and_safe_output(capsys: object) -> None:
    transport = FakeSuccessTransport()
    exit_code = script.main(AUTHORIZED_ENV, transport=transport)

    assert exit_code == 0
    assert len(transport.calls) == 1
    sent_body = transport.calls[0]["body"]
    assert isinstance(sent_body, bytes)
    assert b"Microsoft Sentinel monitoring on a 24/7 basis" in sent_body

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "passed" in captured.out
    assert "technology=microsoft_sentinel" in captured.out
    assert "model=openai/gpt-5.4-mini" in captured.out
    # Safety: no secret, no header, no prompt text in the output.
    assert TEST_SECRET not in captured.out + captured.err
    assert "Bearer" not in captured.out + captured.err
    assert "untrusted" not in captured.out  # prompt text never echoed


def test_failure_prints_only_the_stable_code(capsys: object) -> None:
    class FailingTransport:
        def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
            return OrangeProxyHTTPResult(status_code=401, content_type=None, body=b"denied")

    exit_code = script.main(AUTHORIZED_ENV, transport=FailingTransport())
    assert exit_code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "authentication_failed" in captured.err
    assert "denied" not in captured.err
