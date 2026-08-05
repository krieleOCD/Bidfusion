"""Hardening tests: operator-safe errors, permissions, method limits.

UI error responses never echo raw exception details, UI-created output
directories stay owner-only, and mutating routes accept POST only.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Never, cast

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui import service
from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.registry import RunRegistry

EXPECTED_CSP_MARKER = "default-src 'none'"


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return create_app(output_base=tmp_path / "ui-runs")


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def test_pipeline_errors_render_an_operator_safe_500(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding_run(**_kwargs: object) -> Never:
        raise ValueError("SECRET-DETAIL-THAT-MUST-NOT-LEAK /private/path")

    monkeypatch.setattr(service, "run_package", exploding_run)

    response = client.post("/runs", data={"package": "rfp-minimal"})

    assert response.status_code == 500
    html = response.get_data(as_text=True)
    assert "SECRET-DETAIL-THAT-MUST-NOT-LEAK" not in html
    assert "/private/path" not in html
    assert service.OPERATOR_SAFE_RUN_MESSAGE in html
    assert response.headers["Content-Security-Policy"].startswith(EXPECTED_CSP_MARKER)


def test_error_pages_use_the_branded_layout_and_leak_nothing(client: FlaskClient) -> None:
    response = client.get("/runs/run-404")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "BidFusion" in html
    assert "Back to package selection" in html
    assert "Traceback" not in html


def test_ui_created_run_outputs_stay_owner_only(app: Flask, client: FlaskClient) -> None:
    started = client.post("/runs", data={"package": "rfp-minimal"})
    key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    registry = cast(RunRegistry, app.config["RUN_REGISTRY"])
    record = registry.get(key)
    assert record is not None

    for directory in (record.output_root, record.summary.run_directory):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory
    summary_file = record.summary.run_directory / "run-summary.json"
    assert stat.S_IMODE(summary_file.stat().st_mode) == 0o600


def test_mutating_routes_reject_get(client: FlaskClient) -> None:
    assert client.get("/runs").status_code == 405
    assert client.get("/runs/run-001/process").status_code == 405


def test_cli_server_binds_loopback_and_never_loads_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bidfusion.local_ui.app import main

    captured: dict[str, object] = {}

    def fake_run(self: Flask, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(Flask, "run", fake_run)

    assert main([]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["load_dotenv"] is False
