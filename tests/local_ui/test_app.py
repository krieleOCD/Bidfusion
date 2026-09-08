"""Tests for the Flask app factory: strict security headers, no remote assets.

The UI is a local, server-rendered presentation layer: every response
carries a strict Content-Security-Policy that forbids scripts and any
remote resource, and nothing is cached.
"""

from __future__ import annotations

from bidfusion.local_ui.app import create_app

EXPECTED_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def test_index_responds_and_sets_strict_security_headers() -> None:
    client = create_app().test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == EXPECTED_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_not_found_responses_also_carry_the_security_headers() -> None:
    client = create_app().test_client()

    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
    assert response.headers["Content-Security-Policy"] == EXPECTED_CSP
