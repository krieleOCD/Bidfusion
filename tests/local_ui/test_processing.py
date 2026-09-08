"""Integration tests for the processing view: real stages, real outcomes.

The processing section renders exactly the eight recorded pipeline
stages with their contract outcomes (NOT_ATTEMPTED / SUCCEEDED /
REVIEW_REQUIRED / FAILED). There is no synthetic progress indicator,
and a FAILED run shows neither working- nor review-package content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest
from flask.testing import FlaskClient

import bidfusion.orchestration.local_pipeline as pipeline_module
from bidfusion.local_ui.app import create_app

STAGE_LABELS = (
    "Intake",
    "Preflight",
    "Package gate",
    "Parsing",
    "Extraction",
    "Normalization",
    "Quality gate",
    "Package generation",
)


@pytest.fixture
def client(tmp_path: Path) -> FlaskClient:
    return create_app(output_base=tmp_path / "ui-runs").test_client()


def full_run(client: FlaskClient, package: str) -> str:
    started = client.post("/runs", data={"package": package})
    assert started.status_code == 303
    security_key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    processed = client.post(f"/runs/{security_key}/process")
    assert processed.status_code == 303
    page = client.get(processed.headers["Location"])
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_completed_run_shows_all_stages_as_succeeded(client: FlaskClient) -> None:
    html = full_run(client, "rfp-minimal")

    assert 'class="stage-list"' in html
    for label in STAGE_LABELS:
        assert label in html
    assert html.count("SUCCEEDED") == len(STAGE_LABELS)
    assert "ACCEPTABLE" in html
    assert "bidfusion-mvp-quality-gate" in html


def test_parser_review_run_reports_review_required_stages(client: FlaskClient) -> None:
    html = full_run(client, "rfp-unsupported")

    assert html.count("REVIEW_REQUIRED") >= 2
    assert "NOT_ATTEMPTED" in html
    assert "FAILED" not in html


def test_security_only_run_shows_no_stage_list(client: FlaskClient) -> None:
    started = client.post("/runs", data={"package": "rfp-minimal"})
    page = client.get(started.headers["Location"]).get_data(as_text=True)

    assert 'class="stage-list"' not in page
    assert "NOT_ATTEMPTED" not in page


def test_failed_run_shows_failed_stages_and_no_package_content(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding_extractor(*_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("synthetic extractor crash")

    monkeypatch.setattr(pipeline_module, "extract_formalities", exploding_extractor)
    html = full_run(client, "rfp-minimal")

    assert "Run failed" in html
    assert html.count("FAILED") >= 2
    assert "NOT_ATTEMPTED" in html
    assert "working-package" not in html.lower()
    assert "review-package" not in html.lower()
    assert "synthetic extractor crash" not in html
