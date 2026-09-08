"""Integration tests for the security-review flow of the local UI.

The UI starts real pipeline runs on the synthetic fixtures and renders
only what the versioned run results state: the package gate decision,
per-document verdicts, and — exclusively for a CLEARED, not yet
processed run — the explicit "Run full analysis" action.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return create_app(output_base=tmp_path / "ui-runs")


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _start_security_run(client: FlaskClient, package: str) -> str:
    response = client.post("/runs", data={"package": package})
    assert response.status_code == 303
    location = response.headers["Location"]
    page = client.get(location)
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_cleared_security_run_shows_gate_result_and_full_analysis_action(
    client: FlaskClient,
) -> None:
    html = _start_security_run(client, "rfp-minimal")

    assert "CLEARED" in html
    assert "bidfusion-mvp-local-gate:0.1.0" in html
    assert html.count("ALLOW") >= 3
    assert "rfp-invitation.pdf" in html
    assert "Run full analysis" in html
    assert "new full run of the same synthetic package" in html
    assert "not a production security clearance" in html
    assert 'class="stage-list"' not in html


def test_blocked_package_shows_no_processing_and_no_package_content(
    client: FlaskClient,
) -> None:
    html = _start_security_run(client, "rfp-blocked")

    assert "BLOCKED" in html
    assert "payload.js" in html
    assert "Run full analysis" not in html
    assert 'class="stage-list"' not in html
    assert "working-package" not in html.lower()
    assert "review-package" not in html.lower()
    assert "Back to package selection" in html


def test_blocked_run_directory_is_shown_as_plain_text_not_a_link(
    client: FlaskClient, tmp_path: Path
) -> None:
    html = _start_security_run(client, "rfp-blocked")

    assert 'class="path-code"' in html
    assert 'href="file:' not in html


def test_security_review_pending_package_offers_no_full_analysis(
    client: FlaskClient,
) -> None:
    html = _start_security_run(client, "rfp-review")

    assert "REVIEW_REQUIRED" in html
    assert "Run full analysis" not in html
    assert "working-package" not in html.lower()
    assert "review-package" not in html.lower()


@pytest.mark.parametrize(
    "package",
    ["does-not-exist", "../rfp-minimal", "/etc", "rfp-minimal/../rfp-blocked", ""],
)
def test_unknown_or_manipulated_package_names_yield_404_and_no_run(
    client: FlaskClient, tmp_path: Path, package: str
) -> None:
    response = client.post("/runs", data={"package": package})

    assert response.status_code == 404
    assert not (tmp_path / "ui-runs").exists() or not any((tmp_path / "ui-runs").iterdir())
    assert client.get("/runs/run-001").status_code == 404


def test_unknown_run_keys_yield_404(client: FlaskClient) -> None:
    assert client.get("/runs/run-999").status_code == 404
    assert client.get("/runs/%2e%2e").status_code == 404


def test_full_analysis_action_starts_a_new_full_run(client: FlaskClient) -> None:
    _start_security_run(client, "rfp-minimal")

    response = client.post("/runs/run-001/process")
    assert response.status_code == 303
    location = response.headers["Location"]
    assert location.endswith("/runs/run-002")

    start_page = client.get("/").get_data(as_text=True)
    assert "run-002" in start_page
    assert "Full analysis" in start_page


def test_full_analysis_is_refused_for_runs_without_cleared_gate(
    client: FlaskClient,
) -> None:
    _start_security_run(client, "rfp-blocked")

    response = client.post("/runs/run-001/process")

    assert response.status_code == 409
