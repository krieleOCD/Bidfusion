"""Integration tests for the result views and the download allowlist.

ACCEPTABLE runs render only the working package, REVIEW_REQUIRED runs
only the clearly marked review package. JSON and Markdown are shown
exclusively as escaped preformatted text, downloads are limited to a
static artifact allowlist, and tampered run directories are refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.registry import RunRegistry


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return create_app(output_base=tmp_path / "ui-runs")


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def full_run_key(client: FlaskClient, package: str) -> str:
    started = client.post("/runs", data={"package": package})
    assert started.status_code == 303
    security_key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    processed = client.post(f"/runs/{security_key}/process")
    assert processed.status_code == 303
    return processed.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def run_directory(app: Flask, run_key: str) -> Path:
    registry = cast(RunRegistry, app.config["RUN_REGISTRY"])
    record = registry.get(run_key)
    assert record is not None
    return record.summary.run_directory


def test_completed_run_links_and_renders_the_working_package(
    app: Flask, client: FlaskClient
) -> None:
    key = full_run_key(client, "rfp-minimal")
    run_page = client.get(f"/runs/{key}").get_data(as_text=True)
    assert "Open working package" in run_page

    response = client.get(f"/runs/{key}/working-package")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Working package" in html
    assert "Mandatory requirements" in html
    assert html.count("MUST") >= 4
    assert "rfp-invitation.pdf (p. 2)" in html
    assert "requirements-matrix.xlsx (Requirements!B2)" in html
    assert "2026-09-30" in html
    assert "Submission instructions" in html
    assert "Open questions" in html
    assert "OQ-001" in html
    assert "Executive overview" in html


def test_working_package_json_and_markdown_render_as_escaped_pre(
    client: FlaskClient,
) -> None:
    key = full_run_key(client, "rfp-minimal")

    json_view = client.get(f"/runs/{key}/working-package?view=json").get_data(as_text=True)
    assert 'class="artifact-pre"' in json_view
    assert "bid_id" in json_view

    md_view = client.get(f"/runs/{key}/working-package?view=md").get_data(as_text=True)
    assert 'class="artifact-pre"' in md_view
    assert "# Bid Working Package" in md_view
    assert md_view.count("<h1") == 1
    assert client.get(f"/runs/{key}/working-package?view=other").status_code == 404


def test_working_package_is_only_available_for_completed_runs(
    client: FlaskClient,
) -> None:
    started = client.post("/runs", data={"package": "rfp-minimal"})
    security_key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    assert client.get(f"/runs/{security_key}/working-package").status_code == 404

    review_key = full_run_key(client, "rfp-quality-review")
    assert client.get(f"/runs/{review_key}/working-package").status_code == 404
    assert client.get(f"/runs/{review_key}/review-package").status_code == 200


def test_review_package_is_clearly_marked_and_detailed(client: FlaskClient) -> None:
    key = full_run_key(client, "rfp-quality-review")
    run_page = client.get(f"/runs/{key}").get_data(as_text=True)
    assert "Open review package" in run_page
    assert "Open working package" not in run_page

    html = client.get(f"/runs/{key}/review-package").get_data(as_text=True)

    assert "NOT A COMPLETE BID WORKING PACKAGE" in html
    assert "Required manual actions" in html
    assert "Parser warnings" in html
    assert "Unresolved conflicts" in html
    assert "Detected requirements" in html
    assert "mixed-scan.pdf (p. 1)" in html


def test_unsupported_document_run_shows_review_package_with_affected_document(
    client: FlaskClient,
) -> None:
    key = full_run_key(client, "rfp-unsupported")

    html = client.get(f"/runs/{key}/review-package").get_data(as_text=True)

    assert "NOT A COMPLETE BID WORKING PACKAGE" in html
    assert "blank-scan.pdf" in html


def test_downloads_respect_the_static_allowlist(client: FlaskClient) -> None:
    key = full_run_key(client, "rfp-minimal")

    for name, mimetype in (
        ("working-package.json", "application/json"),
        ("working-package.md", "text/markdown"),
        ("run-summary.json", "application/json"),
        ("quality-gate.json", "application/json"),
        ("package-gate.json", "application/json"),
    ):
        response = client.get(f"/runs/{key}/artifacts/{name}")
        assert response.status_code == 200, name
        assert response.mimetype == mimetype
        assert "attachment" in response.headers["Content-Disposition"]

    for refused in (
        "review-package.json",
        "integrity-manifest.json",
        "inventory.json",
        "canonical",
        "..%2frun-summary.json",
        "working-package.payload.json",
    ):
        assert client.get(f"/runs/{key}/artifacts/{refused}").status_code == 404, refused


def test_downloads_are_outcome_gated_for_security_only_runs(client: FlaskClient) -> None:
    started = client.post("/runs", data={"package": "rfp-minimal"})
    key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

    assert client.get(f"/runs/{key}/artifacts/package-gate.json").status_code == 200
    assert client.get(f"/runs/{key}/artifacts/run-summary.json").status_code == 200
    assert client.get(f"/runs/{key}/artifacts/working-package.json").status_code == 404
    assert client.get(f"/runs/{key}/artifacts/quality-gate.json").status_code == 404


def test_tampered_run_directories_are_refused(app: Flask, client: FlaskClient) -> None:
    key = full_run_key(client, "rfp-minimal")
    markdown = run_directory(app, key) / "working-package" / "working-package.md"
    markdown.write_text("tampered", encoding="utf-8")

    assert client.get(f"/runs/{key}/artifacts/working-package.md").status_code == 409
    assert client.get(f"/runs/{key}/working-package").status_code == 409
    assert client.get(f"/runs/{key}/working-package?view=md").status_code == 409
