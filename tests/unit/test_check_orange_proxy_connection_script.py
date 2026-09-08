"""Offline tests for the standalone Orange Proxy connectivity script.

The script itself is never run under pytest with a real transport — every
test here injects a fake transport (or lets the double opt-in gate stop
execution before any transport is touched). ``tests/conftest.py`` also
blocks real sockets categorically as a structural backstop.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from bidfusion.llm_gateway.orange_proxy import OrangeProxyHTTPResult

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_orange_proxy_connection.py"
TEST_SECRET = "offline-script-test-key"

_AUTHORIZED_ENV = {
    "BIDFUSION_LLM_ENABLED": "true",
    "BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": "true",
    "BIDFUSION_LLM_API_KEY": TEST_SECRET,
}


def _load_script() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "bidfusion_check_orange_proxy_connection_script", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


class ExplodingTransport:
    """Fails the test loudly if the gating logic ever reaches the transport."""

    def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
        raise AssertionError("the connectivity script must not reach the transport here")


class FakeSuccessTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs: object) -> OrangeProxyHTTPResult:
        self.calls.append(kwargs)
        body = json.dumps(
            {
                "id": "chatcmpl-script-test",
                "model": "openai/gpt-5.4-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"title":"ok","items":[],"confidence":1.0}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
        ).encode()
        return OrangeProxyHTTPResult(status_code=200, content_type="application/json", body=body)


class FakeFailureTransport:
    def post(self, **_kwargs: object) -> OrangeProxyHTTPResult:
        return OrangeProxyHTTPResult(status_code=401, content_type="application/json", body=b"{}")


def test_missing_both_flags_is_fail_closed_and_never_touches_the_transport(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = script.main({}, transport=ExplodingTransport())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "skipped" in captured.err.lower()


def test_enabled_without_the_second_opt_in_flag_is_fail_closed() -> None:
    env = {"BIDFUSION_LLM_ENABLED": "true", "BIDFUSION_LLM_API_KEY": TEST_SECRET}

    exit_code = script.main(env, transport=ExplodingTransport())

    assert exit_code == 1


def test_second_opt_in_flag_without_enabled_is_fail_closed() -> None:
    env = {"BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": "true", "BIDFUSION_LLM_API_KEY": TEST_SECRET}

    exit_code = script.main(env, transport=ExplodingTransport())

    assert exit_code == 1


@pytest.mark.parametrize("raw", ["True", "  true  ", "TRUE"])
def test_opt_in_flags_accept_any_casing_or_surrounding_whitespace_of_true(raw: str) -> None:
    transport = FakeSuccessTransport()
    env = {
        **_AUTHORIZED_ENV,
        "BIDFUSION_LLM_ENABLED": raw,
        "BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": raw,
    }

    exit_code = script.main(env, transport=transport)

    assert exit_code == 0
    assert len(transport.calls) == 1


@pytest.mark.parametrize("raw", ["1", "yes", "on"])
def test_opt_in_flags_reject_common_aliases_that_are_not_the_word_true(raw: str) -> None:
    env = {
        **_AUTHORIZED_ENV,
        "BIDFUSION_LLM_ENABLED": raw,
        "BIDFUSION_RUN_EXTERNAL_GATEWAY_TESTS": raw,
    }

    exit_code = script.main(env, transport=ExplodingTransport())

    assert exit_code == 1


def test_both_flags_true_but_invalid_settings_is_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {**_AUTHORIZED_ENV, "BIDFUSION_LLM_DEFAULT_MODEL": "openai/gpt-4"}

    exit_code = script.main(env, transport=ExplodingTransport())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid_configuration" in captured.err


def test_both_flags_true_with_valid_settings_runs_and_reports_only_safe_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = FakeSuccessTransport()

    exit_code = script.main(dict(_AUTHORIZED_ENV), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(transport.calls) == 1
    assert "request_id=" in captured.out
    assert "operation=" in captured.out
    assert "model=" in captured.out
    assert "status=" in captured.out
    assert "duration_ms=" in captured.out
    assert "schema_validation=" in captured.out
    # Never the prompt, never the raw structured content, never the secret.
    assert "synthetic connectivity check" not in captured.out
    assert '"title"' not in captured.out
    assert TEST_SECRET not in captured.out
    assert TEST_SECRET not in captured.err


def test_provider_error_is_translated_to_a_safe_static_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = script.main(dict(_AUTHORIZED_ENV), transport=FakeFailureTransport())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "authentication_failed" in captured.err
    assert TEST_SECRET not in captured.err


def test_authorization_header_never_appears_in_script_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = FakeSuccessTransport()

    script.main(dict(_AUTHORIZED_ENV), transport=transport)

    captured = capsys.readouterr()
    assert "Bearer" not in captured.out
    assert "Bearer" not in captured.err
    assert "authorization" not in captured.out.lower()


def test_script_sends_only_a_synthetic_non_confidential_prompt() -> None:
    transport = FakeSuccessTransport()

    script.main(dict(_AUTHORIZED_ENV), transport=transport)

    # "no customer data" is the deliberate safety disclaimer in the prompt
    # itself, so it is not in this forbidden list — its presence is correct.
    body = json.loads(transport.calls[0]["body"])  # type: ignore[arg-type]
    joined = json.dumps(body)
    for forbidden in ("rfp", "inbox", "results"):
        assert forbidden not in joined.lower()
