"""Offline tests for the Orange Proxy HTTP transport's redirect safety.

No real socket is opened here: ``OrangeNoRedirectHandler.redirect_request``
is exercised directly, and ``tests/conftest.py`` blocks any AF_INET/AF_INET6
socket construction for the whole suite as a structural backstop.
"""

from __future__ import annotations

from urllib.request import Request, build_opener

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayError, LlmGatewayErrorCode
from bidfusion.llm_gateway.orange_proxy import (
    OrangeNoRedirectHandler,
    OrangeProxyHTTPResult,
    UrllibOrangeProxyTransport,
)


def make_request(authorization: str = "Bearer super-secret-token") -> Request:
    return Request(
        url="https://llmproxy.ai.orange/chat/completions",
        data=b"{}",
        headers={"Authorization": authorization, "Content-Type": "application/json"},
        method="POST",
    )


@pytest.mark.parametrize(
    "new_url",
    [
        "https://evil.example.invalid/chat/completions",
        "http://llmproxy.ai.orange/chat/completions",
        "https://user:pass@llmproxy.ai.orange/chat/completions",
        "https://llmproxy.ai.orange/chat/completions?token=leak",
        "https://llmproxy.ai.orange/chat/completions",
    ],
)
def test_redirect_request_always_declines_to_redirect(new_url: str) -> None:
    handler = OrangeNoRedirectHandler()

    result = handler.redirect_request(
        make_request(), fp=None, code=302, msg="Found", headers={}, newurl=new_url
    )

    assert result is None


def test_declining_a_redirect_never_constructs_a_follow_up_request_with_the_auth_header() -> None:
    handler = OrangeNoRedirectHandler()
    original = make_request()

    result = handler.redirect_request(
        original,
        fp=None,
        code=302,
        msg="Found",
        headers={},
        newurl="https://evil.example.invalid/chat/completions",
    )

    # No new Request is ever built, so there is no object that could carry
    # the Authorization header to a different host.
    assert result is None


def test_orange_proxy_http_result_never_includes_body_in_repr() -> None:
    result = OrangeProxyHTTPResult(
        status_code=200, content_type="application/json", body=b"super-secret-body-content"
    )

    assert "super-secret-body-content" not in repr(result)


def test_urllib_transport_installs_the_no_redirect_handler() -> None:
    transport = UrllibOrangeProxyTransport()

    # OpenerDirector.handlers exists at runtime but isn't in typeshed.
    handler_types = {type(handler) for handler in transport.opener.handlers}  # type: ignore[attr-defined]
    assert OrangeNoRedirectHandler in handler_types


def test_no_redirect_handler_replaces_the_default_redirect_handler() -> None:
    from urllib.request import HTTPRedirectHandler

    default_opener = build_opener()
    default_types = {type(handler) for handler in default_opener.handlers}  # type: ignore[attr-defined]

    transport = UrllibOrangeProxyTransport()
    our_types = {type(handler) for handler in transport.opener.handlers}  # type: ignore[attr-defined]

    assert HTTPRedirectHandler in default_types
    assert HTTPRedirectHandler not in our_types  # only our stricter subclass remains


def test_real_transport_rejects_a_malformed_header_before_any_socket_is_opened() -> None:
    # http.client validates header values (rejecting bare CR/LF) before it
    # ever opens a socket, so this exercises the real transport's own
    # ValueError handling without tripping the conftest.py network guard.
    #
    # CPython's real ValueError message here echoes only the offending
    # *value*, never the word "Authorization" — so it is classified via the
    # documented "otherwise" fallback (INVALID_CONFIGURATION), which is a
    # fully valid outcome per the classifier's contract. What matters is
    # covered below: a stable, non-retryable LlmGatewayError with the
    # secret nowhere in it, not one specific code.
    transport = UrllibOrangeProxyTransport()

    with pytest.raises(LlmGatewayError) as raised:
        transport.post(
            url="https://llmproxy.ai.orange/chat/completions",
            headers={
                "authorization": "Bearer synthetic-super-secret\r\nEvil-Header: injected",
                "content-type": "application/json",
            },
            body=b"{}",
            timeout_seconds=1.0,
            request_id="REQ-TRANSPORT-HEADER-001",
        )

    assert raised.value.code in {
        LlmGatewayErrorCode.AUTHENTICATION_FAILED,
        LlmGatewayErrorCode.INVALID_CONFIGURATION,
    }
    assert raised.value.retryable is False
    assert raised.value.request_id == "REQ-TRANSPORT-HEADER-001"
    assert "synthetic-super-secret" not in str(raised.value)
    assert "synthetic-super-secret" not in repr(raised.value)
