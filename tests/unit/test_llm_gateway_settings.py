"""Offline, fail-closed tests for Orange LLM Proxy Gateway settings."""

from __future__ import annotations

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.settings import load_orange_proxy_settings

_VALID_ENV = {
    "BIDFUSION_LLM_PROVIDER": "orange_proxy",
    "BIDFUSION_LLM_BASE_URL": "https://llmproxy.ai.orange",
    "BIDFUSION_LLM_API_KEY": "offline-test-key",
    "BIDFUSION_LLM_DEFAULT_MODEL": "openai/gpt-5.4-mini",
    "BIDFUSION_LLM_TIMEOUT_SECONDS": "60",
    "BIDFUSION_LLM_MAX_RETRIES": "2",
    "BIDFUSION_LLM_ENABLED": "true",
}


def env(**overrides: str) -> dict[str, str]:
    merged = dict(_VALID_ENV)
    merged.update(overrides)
    return merged


def test_missing_enabled_var_defaults_to_disabled() -> None:
    settings = load_orange_proxy_settings({})

    assert settings.enabled is False


def test_disabled_settings_load_without_an_api_key() -> None:
    settings = load_orange_proxy_settings({"BIDFUSION_LLM_ENABLED": "false"})

    assert settings.enabled is False


def test_enabled_true_without_api_key_is_invalid_configuration() -> None:
    with pytest.raises(LlmGatewayError) as raised:
        load_orange_proxy_settings(env(BIDFUSION_LLM_API_KEY=""))

    assert raised.value.code is LlmGatewayErrorCode.INVALID_CONFIGURATION


def test_enabled_true_with_api_key_loads_successfully() -> None:
    settings = load_orange_proxy_settings(env())

    assert settings.enabled is True
    assert settings.provider == "orange_proxy"


# --- L3: documented boolean-parsing semantics -----------------------------
#
# "enabled" parses as whitespace- and case-insensitive equality with the
# literal word "true" — not as "must be exactly the string 'true'", and
# not as an accepted-alias list ("1"/"yes"/"on" are all rejected).


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "  true  ", "TrUe"])
def test_enabled_accepts_any_casing_or_surrounding_whitespace_of_true(raw: str) -> None:
    settings = load_orange_proxy_settings(env(BIDFUSION_LLM_ENABLED=raw))

    assert settings.enabled is True


@pytest.mark.parametrize("raw", ["1", "yes", "on", "True.", "truex", ""])
def test_enabled_rejects_common_aliases_that_are_not_the_word_true(raw: str) -> None:
    settings = load_orange_proxy_settings({"BIDFUSION_LLM_ENABLED": raw})

    assert settings.enabled is False


def test_wrong_provider_is_rejected() -> None:
    with pytest.raises(LlmGatewayError) as raised:
        load_orange_proxy_settings(env(BIDFUSION_LLM_PROVIDER="openai_direct"))

    assert raised.value.code is LlmGatewayErrorCode.INVALID_CONFIGURATION


def test_http_scheme_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_BASE_URL="http://llmproxy.ai.orange"))


def test_foreign_host_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_BASE_URL="https://evil.example.invalid"))


def test_embedded_credentials_in_base_url_are_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(
            env(BIDFUSION_LLM_BASE_URL="https://user:pass@llmproxy.ai.orange")
        )


def test_query_string_in_base_url_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_BASE_URL="https://llmproxy.ai.orange?x=1"))


def test_manipulated_extra_path_in_base_url_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(
            env(BIDFUSION_LLM_BASE_URL="https://llmproxy.ai.orange/evil-path")
        )


def test_trailing_slash_in_base_url_is_tolerated() -> None:
    settings = load_orange_proxy_settings(env(BIDFUSION_LLM_BASE_URL="https://llmproxy.ai.orange/"))

    assert str(settings.provider_config.endpoint) == "https://llmproxy.ai.orange/chat/completions"


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_non_positive_timeout_is_rejected(timeout: str) -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_TIMEOUT_SECONDS=timeout))


def test_timeout_above_the_conservative_upper_bound_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_TIMEOUT_SECONDS="121"))


def test_non_numeric_timeout_is_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_TIMEOUT_SECONDS="not-a-number"))


@pytest.mark.parametrize("retries", ["-1", "3"])
def test_retries_out_of_bounds_are_rejected(retries: str) -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_MAX_RETRIES=retries))


def test_non_numeric_retries_are_rejected() -> None:
    with pytest.raises(LlmGatewayError):
        load_orange_proxy_settings(env(BIDFUSION_LLM_MAX_RETRIES="two"))


def test_disallowed_model_is_rejected() -> None:
    with pytest.raises(LlmGatewayError) as raised:
        load_orange_proxy_settings(env(BIDFUSION_LLM_DEFAULT_MODEL="openai/gpt-4"))

    assert raised.value.code is LlmGatewayErrorCode.INVALID_CONFIGURATION


def test_secret_value_never_appears_in_settings_repr() -> None:
    settings = load_orange_proxy_settings(env(BIDFUSION_LLM_API_KEY="super-secret-value"))

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)


def test_defaults_match_the_documented_env_var_table_when_all_vars_absent() -> None:
    settings = load_orange_proxy_settings({})

    assert settings.provider == "orange_proxy"
    assert settings.default_model == "openai/gpt-5.4-mini"
    assert settings.max_retries == 2
    assert str(settings.provider_config.endpoint) == "https://llmproxy.ai.orange/chat/completions"


def test_chat_completions_endpoint_is_exact() -> None:
    settings = load_orange_proxy_settings(env())

    assert str(settings.provider_config.endpoint) == "https://llmproxy.ai.orange/chat/completions"


def test_loader_never_reads_a_dotenv_file() -> None:
    # The loader only reads from the explicit mapping passed in — an empty
    # mapping must resolve to compiled-in defaults, never fall through to
    # any on-disk .env file.
    settings = load_orange_proxy_settings({})

    assert settings.enabled is False
    assert settings.default_model == "openai/gpt-5.4-mini"
